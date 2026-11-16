import aws_cdk as cdk
from aws_cdk.assertions import Template

from infrastructure.site_stack import HumbleChuckSiteStack
from site_builder.build import build


def test_recordings_have_private_storage_and_uncached_cloudfront_routes(tmp_path):
    build()
    app = cdk.App(outdir=str(tmp_path / "cdk.out"))
    stack = HumbleChuckSiteStack(app, "TestSite", env=cdk.Environment(account="559681045665", region="us-east-1"))
    template = Template.from_stack(stack)
    template.has_resource_properties("AWS::S3::Bucket", {
        "BucketName": "humblechuck-recordings-559681045665-us-east-1",
        "VersioningConfiguration": {"Status": "Enabled"},
        "PublicAccessBlockConfiguration": {"BlockPublicAcls": True, "BlockPublicPolicy": True, "IgnorePublicAcls": True, "RestrictPublicBuckets": True},
    })
    resources = template.to_json()["Resources"]
    recordings_id, recordings = next((key, value) for key, value in resources.items() if value["Type"] == "AWS::S3::Bucket" and "BucketName" in value["Properties"])
    assert recordings["DeletionPolicy"] == "Retain"
    distribution = next(value for value in resources.values() if value["Type"] == "AWS::CloudFront::Distribution")
    behaviors = {item["PathPattern"]: item for item in distribution["Properties"]["DistributionConfig"]["CacheBehaviors"]}
    for path in ("/api/demos", "/tracks/*"):
        assert behaviors[path]["CachePolicyId"] == "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
        assert not behaviors[path].get("FunctionAssociations")
    template.has_resource_properties("AWS::Lambda::Url", {"AuthType": "AWS_IAM"})
    permissions = [value["Properties"] for value in resources.values() if value["Type"] == "AWS::Lambda::Permission"]
    for action in ("lambda:InvokeFunctionUrl", "lambda:InvokeFunction"):
        assert any(item["Action"] == action and item["Principal"] == "cloudfront.amazonaws.com" and "SourceArn" in item for item in permissions)
    deployments = [value for value in resources.values() if value["Type"] == "Custom::CDKBucketDeployment"]
    assert all(value["Properties"]["DestinationBucketName"] != {"Ref": recordings_id} for value in deployments)
    app.synth()
