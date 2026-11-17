from pathlib import Path

from aws_cdk import (
    CfnOutput,
    Duration,
    Fn,
    RemovalPolicy,
    Stack,
    aws_certificatemanager as acm,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_route53 as route53,
    aws_route53_targets as targets,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
)
from constructs import Construct


class HumbleChuckSiteStack(Stack):
    """Private S3 origin, CloudFront CDN, DNS, and GitHub deployment role."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        domain_name = self.node.try_get_context("domain_name") or "humblechuck.com"
        enable_domain = self._as_bool(self.node.try_get_context("enable_domain"))

        site_dir = Path(__file__).resolve().parents[1] / "dist"
        if not (site_dir / "index.html").exists():
            raise FileNotFoundError(
                "dist/index.html is missing. Run `python -m site_builder.build` first."
            )

        bucket = s3.Bucket(
            self,
            "SiteBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
            auto_delete_objects=False,
        )

        recordings = s3.Bucket(
            self,
            "RecordingsBucket",
            bucket_name=f"humblechuck-recordings-{self.account}-{self.region}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
            auto_delete_objects=False,
        )
        # Only the first recording and its setup marker are writable by CI.
        # Subsequent track uploads are managed independently of site deploys.
        recordings.add_to_resource_policy(iam.PolicyStatement(
            principals=[iam.ArnPrincipal(
                f"arn:{self.partition}:iam::{self.account}:role/humblechuck-github-actions"
            )],
            actions=["s3:GetObject", "s3:PutObject"],
            resources=[
                recordings.arn_for_objects("tracks/peace-i-seek-take-6.m4a"),
                recordings.arn_for_objects("setup/initial-recording-v1"),
            ],
        ))
        # S3 needs ListBucket permission to return 404 (rather than 403) for
        # a missing setup marker during the first deployment.
        recordings.add_to_resource_policy(iam.PolicyStatement(
            principals=[iam.ArnPrincipal(
                f"arn:{self.partition}:iam::{self.account}:role/humblechuck-github-actions"
            )],
            actions=["s3:ListBucket"], resources=[recordings.bucket_arn],
        ))
        catalog = lambda_.Function(
            self,
            "DemosCatalog",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="catalog.handler",
            code=lambda_.Code.from_asset(str(Path(__file__).parent / "demos"), exclude=["__pycache__", "*.pyc"]),
            memory_size=256,
            timeout=Duration.seconds(15),
            environment={"RECORDINGS_BUCKET": recordings.bucket_name},
        )
        catalog.add_to_role_policy(iam.PolicyStatement(
            actions=["s3:ListBucketVersions"],
            resources=[recordings.bucket_arn],
            conditions={"StringLike": {"s3:prefix": ["tracks/*"]}},
        ))
        catalog_url = catalog.add_function_url(auth_type=lambda_.FunctionUrlAuthType.AWS_IAM)

        zone = route53.PublicHostedZone(
            self,
            "HostedZone",
            zone_name=domain_name,
            comment="DNS for humblechuck.com; registrar remains at Squarespace.",
        )
        route53.TxtRecord(
            self,
            "OpenAIDomainVerification",
            zone=zone,
            record_name=domain_name,
            values=["openai-domain-verification=dv-xgPlu6q663J6QawEyVMPKzCR"],
            ttl=Duration.minutes(5),
        )

        certificate = None
        aliases = None
        if enable_domain:
            certificate = acm.Certificate(
                self,
                "Certificate",
                domain_name=domain_name,
                subject_alternative_names=[f"www.{domain_name}"],
                validation=acm.CertificateValidation.from_dns(zone),
            )
            aliases = [domain_name, f"www.{domain_name}"]

        distribution = cloudfront.Distribution(
            self,
            "Distribution",
            default_root_object="index.html",
            domain_names=aliases,
            certificate=certificate,
            minimum_protocol_version=cloudfront.SecurityPolicyProtocol.TLS_V1_2_2021,
            http_version=cloudfront.HttpVersion.HTTP2_AND_3,
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD_OPTIONS,
                cached_methods=cloudfront.CachedMethods.CACHE_GET_HEAD_OPTIONS,
                compress=True,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                function_associations=[
                    cloudfront.FunctionAssociation(
                        function=cloudfront.Function(
                            self,
                            "CleanUrlRewrite",
                            code=cloudfront.FunctionCode.from_inline(
                                """function handler(event) {
  var request = event.request;
  var uri = request.uri;
  if (uri.endsWith('/')) {
    request.uri += 'index.html';
  } else if (!uri.split('/').pop().includes('.')) {
    request.uri += '/index.html';
  }
  return request;
}"""
                            ),
                        ),
                        event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
                    )
                ],
            ),
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_http_status=404,
                    response_page_path="/404.html",
                    ttl=Duration.seconds(0),
                ),
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=404,
                    response_page_path="/404.html",
                    ttl=Duration.seconds(0),
                ),
            ],
        )

        distribution.add_behavior(
            "/api/demos",
            origins.FunctionUrlOrigin.with_origin_access_control(catalog_url),
            viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD_OPTIONS,
            cache_policy=cloudfront.CachePolicy(
                self, "DemosCatalogCache",
                min_ttl=Duration.seconds(0),
                default_ttl=Duration.seconds(15),
                max_ttl=Duration.seconds(15),
                enable_accept_encoding_gzip=True,
                enable_accept_encoding_brotli=True,
            ),
            compress=True,
        )
        # New function URLs require both invocation permissions. The pinned
        # CDK origin helper grants InvokeFunctionUrl; grant the second here.
        catalog.add_permission(
            "CloudFrontInvokeFunction",
            principal=iam.ServicePrincipal("cloudfront.amazonaws.com"),
            action="lambda:InvokeFunction",
            source_arn=distribution.distribution_arn,
            invoked_via_function_url=True,
        )
        distribution.add_behavior(
            "/tracks/*",
            origins.S3BucketOrigin.with_origin_access_control(recordings,
                origin_access_levels=[cloudfront.AccessLevel.READ, cloudfront.AccessLevel.READ_VERSIONED],
            ),
            viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD_OPTIONS,
            # Real S3 version IDs make each recording URL stable. Newly uploaded
            # replacements receive a new URL as soon as the catalog refreshes.
            cache_policy=cloudfront.CachePolicy(
                self, "RecordingVersionCache",
                query_string_behavior=cloudfront.CacheQueryStringBehavior.allow_list("versionId"),
                min_ttl=Duration.hours(1),
                default_ttl=Duration.days(1),
                max_ttl=Duration.days(1),
            ),
            response_headers_policy=cloudfront.ResponseHeadersPolicy(
                self, "RecordingHeaders",
                custom_headers_behavior=cloudfront.ResponseCustomHeadersBehavior(
                    custom_headers=[cloudfront.ResponseCustomHeader(
                        header="Cache-Control", value="public, max-age=3600", override=True,
                    )],
                ),
            ),
        )

        if enable_domain:
            cloudfront_target = route53.RecordTarget.from_alias(
                targets.CloudFrontTarget(distribution)
            )
            route53.ARecord(
                self,
                "ApexWebRecord",
                zone=zone,
                record_name=domain_name,
                target=cloudfront_target,
            )
            route53.ARecord(
                self,
                "WwwWebRecord",
                zone=zone,
                record_name=f"www.{domain_name}",
                target=cloudfront_target,
            )
            for construct_id, record_name in [
                ("ApexIpv6Record", domain_name),
                ("WwwIpv6Record", f"www.{domain_name}"),
            ]:
                route53.AaaaRecord(
                    self,
                    construct_id,
                    zone=zone,
                    record_name=record_name,
                    target=cloudfront_target,
                )
        else:
            route53.ARecord(
                self,
                "ApexWebRecord",
                zone=zone,
                record_name=domain_name,
                target=route53.RecordTarget.from_ip_addresses(
                    "198.185.159.145",
                    "198.49.23.144",
                    "198.49.23.145",
                    "198.185.159.144",
                ),
                ttl=Duration.minutes(5),
            )
            route53.CnameRecord(
                self,
                "WwwWebRecord",
                zone=zone,
                record_name=f"www.{domain_name}",
                domain_name="ext-sq.squarespace.com",
                ttl=Duration.minutes(5),
            )

        s3deploy.BucketDeployment(
            self,
            "DeployWebsite",
            sources=[s3deploy.Source.asset(str(site_dir))],
            destination_bucket=bucket,
            distribution=distribution,
            distribution_paths=["/*"],
            prune=True,
        )

        CfnOutput(self, "CloudFrontUrl", value=f"https://{distribution.domain_name}")
        CfnOutput(self, "RecordingsBucketName", value=recordings.bucket_name)
        CfnOutput(self, "RecordingsPrefix", value="tracks/")
        CfnOutput(self, "HostedZoneId", value=zone.hosted_zone_id)
        for index in range(4):
            CfnOutput(
                self,
                f"NameServer{index + 1}",
                value=Fn.select(index, zone.hosted_zone_name_servers),
            )
        CfnOutput(self, "DomainEnabled", value=str(enable_domain).lower())

    @staticmethod
    def _as_bool(value: object) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).lower() in {"1", "true", "yes", "on"}
