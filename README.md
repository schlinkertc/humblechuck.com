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

## Demo play events

The player counts a **qualified play after 10 seconds of actual listening**,
once per listen. Replaying after a song ends, returning to it after selecting
another song, reloading the page, or seeking back to the beginning (within the
first second, from beyond the first second) starts a new listen with its own
10-second threshold. Pause/resume, buffering, and ordinary scrubbing continue
the same listen. Seeking does not add listening time, and a long listen only
counts once. Counts appear under the cued song's title and refresh every 30
seconds while the tab is visible, and on returning to it. Replacing the audio at the
same S3 key keeps its total, while each event identifies the version played.
Renaming a recording changes its ID and starts a new total.

The browser sends `POST /api/demo-plays` with a random UUID, demo ID, listening
duration, track duration when known, recording version, page path, and external
referral **hostname only** when available. The Lambda assigns `played_at` in UTC
and the `qualified_play` event type. No visitor ID, email, cookie, IP address,
full referrer URL, or user agent is stored in the play table. Only pending event
payloads are saved in `sessionStorage`, using a separate UUID for each qualified
listen. Acknowledged events leave the retry queue immediately; they never
suppress subsequent listens. If browser storage is unavailable, retries last
for the current page only. Partial listening progress is kept in memory, so a
reload before qualification starts its 10 seconds again.

One DynamoDB transaction conditionally inserts the event and increments both
the all-time and UTC daily counters. Retries reuse the event ID, including after
a reload or across midnight, and cannot increment counters twice. Requests are
retried up to three times per page load on network failures, HTTP 429, and server
errors. Playback continues if analytics is unavailable. Counts are approximate:
blocked requests can be missed and public browser events can be fabricated.
The Lambda validates inputs and checks the recording exists in S3. It uses the
account's shared Lambda concurrency rather than a per-function limit of two,
so simultaneous listeners and counter reads can proceed together.

`GET /api/demo-plays?demo_id=tracks%2Fpeace-i-seek-take-6.m4a` returns only the
current total. Both API methods bypass CloudFront caching. The function URL is
IAM-protected and accepts invocations only through CloudFront OAC. POST requests
include the SHA-256 of their exact body, as required by Lambda URL OAC; there
are no AWS credentials in browser code.

The stack output **DemoPlayEventsTableName** identifies the private, on-demand
DynamoDB table. It is retained on deletion/replacement and has point-in-time
recovery enabled. There is no automatic expiry of events or counters. To inspect
data using your AWS account permissions, open DynamoDB → Explore items:

- Partition key `pk`: `DEMO#tracks/peace-i-seek-take-6.m4a` (substitute the song's S3 key).
- Sort key `sk`: `TOTAL`, `DAY#2026-11-24`, or `PLAY#<event UUID>`.
- Select index `by-demo-time` and query that partition with a `played_at` range
  to examine individual plays chronologically. Timestamps use ISO 8601 UTC,
  e.g. `2026-11-24T00:00:00.000Z` through `2026-11-24T23:59:59.999Z`.

Raw event queries require AWS permissions and have no public API. The handler
can only insert events, update counters, read totals, and check recording metadata;
it has no table scan, query, or delete permission. Table creation and endpoint
deployment run through the existing GitHub Actions deployment on `main`.

The local preview server simulates play totals in memory, with no AWS access.
Restarting the server clears its counts; replay a song to test another qualified
play in the same tab. This change adds play storage only; show content continues
to come from the existing content files.

## Safety notes

- The content bucket is private and reachable only through CloudFront Origin Access Control.
- The GitHub role trusts only the `main` branch of this repository. It can bootstrap the standard CDK roles, then delegates deployments to those roles.
- The deployment workflow refuses to run unless AWS confirms account `559681045665`, preventing an accidental deployment to the configured work account.
- The S3 bucket is retained if the CloudFormation stack is deleted, preventing accidental loss.
- The domain flag starts off disabled so CloudFormation does not wait for certificate validation before the nameserver cutover.
- Existing non-web DNS records are preserved in Route 53 before the nameserver cutover.
- Until the custom domain is enabled, Route 53 mirrors the existing Squarespace web records to avoid downtime during nameserver propagation.
