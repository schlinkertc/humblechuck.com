#!/usr/bin/env python3
import aws_cdk as cdk

from infrastructure.site_stack import HumbleChuckSiteStack


app = cdk.App(outdir="cdk.out")

HumbleChuckSiteStack(
    app,
    "HumbleChuckSite",
    env=cdk.Environment(
        account=app.node.try_get_context("account"),
        region=app.node.try_get_context("region") or "us-east-1",
    ),
)

app.synth()
