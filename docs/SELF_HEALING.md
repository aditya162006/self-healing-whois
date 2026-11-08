# Architecture and operations

## In-memory components

`WhoisEntry.parse()` observes missing expiration extraction. The client queues
the response without blocking and deduplicates identical parser-scope/text pairs.
A background thread requests and validates a rule, then publishes compiled rules
under a lock into a process-local cache. No runtime state is written to files.

The direct-key API requires key, model, and endpoint. Credentials stay in memory.
The verification script can read an existing `.env`; environment variables take
precedence. The historical JSON corpus is read-only input, not runtime storage.

## Return behavior

`self_healing_whois.enable_healing(...)` defaults to waiting for missing expiration extraction
to be repaired. `self_healing_whois.whois()` raises `WhoisHealingError` on rejection, failure,
queue saturation, cancellation, or repair timeout. Native successful lookups do
not wait for the model. Multiple callers with the same response share one job.

`wait_for_repair=False` returns partial results immediately. Keep the application
alive and repeat the lookup after the repair. Direct `WhoisEntry.load()` remains
non-waiting to avoid recursion during validation. It does not call the public
lookup's waiting step.

## Lifecycle and bounds

Initialize once per process after forking. There is no external worker or
cross-process cache. Disabling healing clears queued responses, job status,
rules, and accepted examples, and wakes blocked callers. An in-flight HTTP
request cannot be cancelled, but cannot publish results after shutdown.
A new client starts with no learned rules.

Defaults: 256 queued jobs, up to 513 retained job records, 128 rule scopes, eight
rules and 32 accepted examples per scope. Completed job records can be evicted;
active records are not evicted. Completed jobs release raw response text except
for the bounded accepted examples used for regression validation. More than
32 KiB of response text is not submitted. Scope/example/rule limits reject new
repairs conservatively rather than discarding their validation history.

One model attempt is made per distinct retained failure. Failures and rejections
remain deduplicated in the current cache. Restart healing to retry; eviction of a
completed record can also allow a later attempt. This prevents an outage from
creating a tight loop of repeated API calls. No jobs survive application exit.

## Validation

Each proposal contains a label, regex, and exact date evidence. The regex must
match the fixed bounded template with an escaped literal English expiration
label. One unambiguous recognized date must appear in the response. Rules are
scoped by parser class and final domain suffix. Native successes always win.

Historical positive coverage is required. Same-scope fixtures, earlier accepted
examples, and incomplete-date negatives are checked. Rules supplement the
parser; Python source is never rewritten. This is regression protection, not
a proof of correctness for every future response.

## Diagnostics

Keep the client returned by `enable_healing()`. For an entry parsed while that
client was running, `client.job_status(entry)` returns a snapshot with `status`,
`attempts`, and sanitized `error`, or `None` if no retained job exists.
Statuses include pending, working, accepted, rejected, failed, and cancelled.
`client.dropped` counts submissions dropped because memory limits were reached.

Provider HTTP 400/401/403 can indicate request/authentication/access problems;
402 indicates billing, 404 an unavailable model/endpoint, 429 quota, and 503 or
timeout service/network unavailability. A provider failure does not prove that
the key is valid. Rejection can indicate unsupported grammar, wrong evidence,
historical regression, model abstention, or insufficient historical coverage.

## Data handling

Raw failed responses go to the configured provider and can include personal
contact information. The library does not save those responses locally; the
provider's own retention policy still applies. Credentials and `.env` should
not be committed. Learned repairs are intentionally temporary.

## Corpus and evaluation

`python scripts/build_healing_corpus.py` rebuilds the bundled JSON from upstream
raw/expected fixtures. This explicit development tool writes a test-data file;
normal library use never updates it. Review its diff before accepting changes.

The default suite uses fake providers and is offline. The live verification
tool tests a synthetic label change with known expected dates. A successful
native live-domain lookup does not test AI repair. Production reliability and
general repair success rates have not been benchmarked.
