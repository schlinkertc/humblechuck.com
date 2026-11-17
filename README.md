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

1. In the personal AWS account, open CloudFormation in `us-east-1`, choose **Create stack → With new resources**, and upload `bootstrap/github-oidc.yaml`. Name the stack `humblechuck-github-trust`, keep the personal GitHub owner/repository names and immutable IDs supplied by the template, acknowledge the IAM capability, and create it. This one-time console step establishes trust; it does not deploy the site.
2. Copy the stack's `GitHubDeployRoleArn` output into a GitHub repository variable named `AWS_DEPLOY_ROLE_ARN`. Add `AWS_ACCOUNT_ID=559681045665` and `ENABLE_DOMAIN=false` as two more repository variables.
3. Push to `main`. GitHub Actions bootstraps CDK inside AWS, tests the site, and deploys the first CloudFront URL. No local AWS deployment command is needed.
4. Copy the four `NameServer` values from the `HumbleChuckSite` CloudFormation stack outputs. In Squarespace Domains, replace the domain's custom nameservers with those Route 53 nameservers. Do not remove or transfer the registration.
5. After public DNS shows the new nameservers, set the GitHub repository variable `ENABLE_DOMAIN=true` and merge the next site change into `main`. The action obtains the certificate and attaches `humblechuck.com` and `www.humblechuck.com`.

## Editing the site

Most copy and project links live in `site_src/content.json`. Layout and metadata are in `site_src/index.html`; visual design is in `site_src/styles.css`.

## Demos and recording uploads

The `/demos` page discovers recordings from S3 at request time. No site build or
code deployment is needed when adding, replacing, or deleting audio.

- **Account / region:** personal account `559681045665`, `us-east-1`.
- **Bucket:** `humblechuck-recordings-559681045665-us-east-1`.
- **Upload folder:** `tracks/`.
- **First track:** `tracks/peace-i-seek-take-6.m4a` → “Peace I Seek — Take 6”.
- **Accepted extensions:** M4A, MP3, WAV, OGG, FLAC, AAC, and OPUS. Browser codec support varies; M4A/AAC and MP3 are the preferred formats.

In the AWS S3 console, open this bucket, open `tracks/`, and upload an audio file.
Use descriptive filenames such as `my-next-song-take-2.m4a`; the player derives
titles from filenames and lists tracks alphabetically. Replace the same filename
to update a recording. Delete its current S3 object to remove it from the list.
S3 versioning keeps old versions available for recovery.

The page checks for changes every 30 seconds while visible and when returning to
the tab. The catalog is cached for 15 seconds, so changes normally appear within
45 seconds; the browser's Reload action also checks the catalog. Currently playing
audio is not interrupted; the replacement is loaded when recued. Streaming and
downloads use the exact S3 object version in each URL. This allows CDN caching
without stale replacements or mixed byte ranges; replacing a key does not
require a CloudFront invalidation. Old URLs may remain accessible because S3
retains prior versions. The player has an explicit Play/Pause/Retry button plus
native scrubbing and volume controls, previous/next, and 15-second skips. Audio
preloading is set to `none`; browsers may still choose to fetch metadata. The
explicit Play button prepares and starts playback within the user's tap.

Each recording has a **Share** link beside its download link. Sharing opens the
device's native share sheet when supported, otherwise copies the link; if clipboard
access is blocked, a selectable link is shown. URLs such as
`https://humblechuck.com/demos#all-the-flowers` cue the named recording after the
catalog loads without autoplaying. Links are based on filenames and survive audio
replacements; renaming a file changes its song link. Missing song links show a
message rather than silently cueing another recording. Ambiguous filenames get
distinct links containing their full S3 keys.

The existing M4As are optimized for streaming (their playback index precedes the
audio) without re-encoding. On macOS, new M4As can be prepared with
`afconvert -f m4af -d 0 input.m4a optimized.m4a` before upload. The `0` data format
copies compressed packets rather than re-encoding them. Unoptimized uploads still
work, but can require more requests before playback starts. The site serves its
existing Manrope and DM Mono fonts locally; licenses are in `site_src/fonts/`.

The recordings bucket is private, retained on stack deletion, and separate from
the website deployment's pruning. CloudFront uses Origin Access Control for both
audio and the catalog Lambda URL. The catalog can only list versions in `tracks/`,
and only returns the latest nondeleted audio files. Everything in `tracks/` with a supported audio extension is
publicly playable and downloadable through the website.

On the first deployment, GitHub Actions uploads the supplied song from
`recordings/seed/` and writes `setup/initial-recording-v1`. Future deployments
leave recordings untouched, including replacements and deletions. Do not delete
the setup marker. The CI upload permission covers only the initial song and marker;
it does not grant write access to other recordings. All infrastructure deployment
continues through GitHub Actions on `main`.

For local playback QA, run `python scripts/preview_demos.py` after building.
This serves the supplied recording locally and simulates the live catalog;
the sample is not copied into the static website build.

## Safety notes

- The content bucket is private and reachable only through CloudFront Origin Access Control.
- The GitHub role trusts only the `main` branch of this repository. It can bootstrap the standard CDK roles, then delegates deployments to those roles.
- The deployment workflow refuses to run unless AWS confirms account `559681045665`, preventing an accidental deployment to the configured work account.
- The S3 bucket is retained if the CloudFormation stack is deleted, preventing accidental loss.
- The domain flag starts off disabled so CloudFormation does not wait for certificate validation before the nameserver cutover.
- Existing non-web DNS records are preserved in Route 53 before the nameserver cutover.
- Until the custom domain is enabled, Route 53 mirrors the existing Squarespace web records to avoid downtime during nameserver propagation.
