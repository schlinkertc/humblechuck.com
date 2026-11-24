import aws_cdk as cdk
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk.assertions import Template

from infrastructure.site_stack import HumbleChuckSiteStack
from site_builder.build import build


def test_recordings_have_private_storage_and_versioned_cloudfront_caching(tmp_path):
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
    assert all(item['ErrorCachingMinTTL'] == 0 for item in distribution['Properties']['DistributionConfig']['CustomErrorResponses'])
    behaviors = {item["PathPattern"]: item for item in distribution["Properties"]["DistributionConfig"]["CacheBehaviors"]}
    for path in ("/api/demos", "/api/demo-plays", "/tracks/*"):
        assert not behaviors[path].get("FunctionAssociations")
    policies = {key: value["Properties"]["CachePolicyConfig"] for key, value in resources.items() if value["Type"] == "AWS::CloudFront::CachePolicy"}
    api_cache = policies[behaviors['/api/demos']['CachePolicyId']['Ref']]
    assert api_cache['MinTTL'] == 0 and api_cache['MaxTTL'] == 15
    media_cache = policies[behaviors['/tracks/*']['CachePolicyId']['Ref']]
    assert media_cache['MinTTL'] == 3600
    assert media_cache['ParametersInCacheKeyAndForwardedToOrigin']['QueryStringsConfig'] == {'QueryStringBehavior': 'whitelist', 'QueryStrings': ['versionId']}
    bucket_policies = [value['Properties']['PolicyDocument'] for value in resources.values() if value['Type'] == 'AWS::S3::BucketPolicy']
    assert 's3:GetObjectVersion' in str(bucket_policies)
    roles = [value['Properties']['PolicyDocument'] for value in resources.values() if value['Type'] == 'AWS::IAM::Policy']
    assert 's3:ListBucketVersions' in str(roles)
    template.has_resource_properties("AWS::Lambda::Url", {"AuthType": "AWS_IAM"})
    permissions = [value["Properties"] for value in resources.values() if value["Type"] == "AWS::Lambda::Permission"]
    for action in ("lambda:InvokeFunctionUrl", "lambda:InvokeFunction"):
        assert any(item["Action"] == action and item["Principal"] == "cloudfront.amazonaws.com" and "SourceArn" in item for item in permissions)
    deployments = [value for value in resources.values() if value["Type"] == "Custom::CDKBucketDeployment"]
    assert all(value["Properties"]["DestinationBucketName"] != {"Ref": recordings_id} for value in deployments)
    play_table_id, play_table = next((key, value) for key, value in resources.items() if value["Type"] == "AWS::DynamoDB::Table")
    assert play_table["DeletionPolicy"] == "Retain"
    assert play_table["UpdateReplacePolicy"] == "Retain"
    table = play_table["Properties"]
    assert table["BillingMode"] == "PAY_PER_REQUEST"
    assert table["PointInTimeRecoverySpecification"]["PointInTimeRecoveryEnabled"] is True
    assert table["KeySchema"] == [{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}]
    assert table["GlobalSecondaryIndexes"][0]["IndexName"] == "by-demo-time"
    assert table["GlobalSecondaryIndexes"][0]["KeySchema"] == [{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "played_at", "KeyType": "RANGE"}]
    plays_lambda = next(value for value in resources.values() if value["Type"] == "AWS::Lambda::Function" and value["Properties"].get("Handler") == "plays.handler")
    assert plays_lambda["Properties"]["Environment"]["Variables"]["PLAY_EVENTS_TABLE"] == {"Ref": play_table_id}
    assert plays_lambda["Properties"]["ReservedConcurrentExecutions"] == 2
    plays_behavior = behaviors["/api/demo-plays"]
    assert "POST" in plays_behavior["AllowedMethods"]
    assert plays_behavior["CachePolicyId"] == cloudfront.CachePolicy.CACHING_DISABLED.cache_policy_id
    origin_policy = resources[plays_behavior["OriginRequestPolicyId"]["Ref"]]["Properties"]["OriginRequestPolicyConfig"]
    assert origin_policy["HeadersConfig"] == {"HeaderBehavior": "whitelist", "Headers": ["Content-Type", "x-amz-content-sha256"]}
    assert origin_policy["QueryStringsConfig"] == {"QueryStringBehavior": "whitelist", "QueryStrings": ["demo_id"]}
    assert origin_policy["CookiesConfig"]["CookieBehavior"] == "none"
    dynamodb_statements = [statement for role in roles for statement in role["Statement"] if isinstance(statement.get("Action"), list) and any(action.startswith("dynamodb:") for action in statement["Action"])]
    assert len(dynamodb_statements) == 1
    assert set(dynamodb_statements[0]["Action"]) == {"dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:GetItem"}
    assert dynamodb_statements[0]["Resource"] == {"Fn::GetAtt": [play_table_id, "Arn"]}
    assert all(value["Properties"]["AuthType"] == "AWS_IAM" for value in resources.values() if value["Type"] == "AWS::Lambda::Url")
    app.synth()
