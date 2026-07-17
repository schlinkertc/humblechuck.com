# humblechuck.com

The replacement for the Squarespace site at `humblechuck.com`: a small static site built with Python and deployed to a private S3 origin behind CloudFront.

## Architecture

- Python builds the site from structured content in `site_src/content.json`.
- AWS CDK, also in Python, defines S3, CloudFront, Route 53, TLS, and the GitHub deployment role.
- GitHub Actions tests every change and deploys every push to `main` using short-lived AWS credentials through OpenID Connect.
- Squarespace remains the registrar. Route 53 becomes the DNS host after a deliberate nameserver change.

## Local development

```bash
uv sync --dev
uv run python -m site_builder.build
uv run python -m http.server 8000 --directory dist
```

Open <http://localhost:8000>.

Run the tests with:

```bash
uv run pytest
```

## First deployment — GitHub only

No site or infrastructure deployment runs from a local machine.

1. In the personal AWS account, open CloudFormation in `us-east-1`, choose **Create stack → With new resources**, and upload `bootstrap/github-oidc.yaml`. Name the stack `humblechuck-github-trust`, acknowledge the IAM capability, and create it. This one-time console step establishes trust; it does not deploy the site.
2. Copy the stack's `GitHubDeployRoleArn` output into a GitHub repository variable named `AWS_DEPLOY_ROLE_ARN`. Add `AWS_ACCOUNT_ID=559681045665` and `ENABLE_DOMAIN=false` as two more repository variables.
3. Push to `main`. GitHub Actions bootstraps CDK inside AWS, tests the site, and deploys the first CloudFront URL. No local AWS deployment command is needed.
4. Copy the four `NameServer` values from the `HumbleChuckSite` CloudFormation stack outputs. In Squarespace Domains, replace the domain's custom nameservers with those Route 53 nameservers. Do not remove or transfer the registration.
5. After public DNS shows the new nameservers, set the GitHub repository variable `ENABLE_DOMAIN=true` and merge the next site change into `main`. The action obtains the certificate and attaches `humblechuck.com` and `www.humblechuck.com`.

## Editing the site

Most copy and project links live in `site_src/content.json`. Layout and metadata are in `site_src/index.html`; visual design is in `site_src/styles.css`.

## Safety notes

- The content bucket is private and reachable only through CloudFront Origin Access Control.
- The GitHub role trusts only the `main` branch of this repository. It can bootstrap the standard CDK roles, then delegates deployments to those roles.
- The deployment workflow refuses to run unless AWS confirms account `559681045665`, preventing an accidental deployment to the configured work account.
- The S3 bucket is retained if the CloudFormation stack is deleted, preventing accidental loss.
- The domain flag starts off disabled so CloudFormation does not wait for certificate validation before the nameserver cutover.
