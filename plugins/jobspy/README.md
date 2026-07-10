# JobSpy plugin

The JobSpy plugin monitors public job listings, stores each listing once, and
ranks it against CV/profile text saved in Evonic's plugin settings. The profile
text and alert routing values remain installation-local and must not be committed.

## Requirements

- Python 3.10 or newer.
- `python-jobspy>=1.1.82,<1.2`, installed through Evonic's `requirements.txt`.
- An optional Evonic default model for hybrid reranking.
- An optional active Evonic agent channel for high-match alerts.

Enable JobSpy from Evonic's Plugins page, then open **JobSpy** in the main
navigation. Add CV/profile text under **Matching and alert settings** and create
one or more saved searches. Profile text, search profiles, results, and routing
identifiers are stored in the local Evonic databases and are not part of this
plugin's source files.

JobSpy currently supports LinkedIn, Indeed, Glassdoor, Google Jobs,
ZipRecruiter, Bayt, Naukri, and BDJobs depending on the installed release and
the options used. It does not support Upwork, Freelancer, PeoplePerHour, or
automatic applications.

## Suggested mobile-development search

Start with a conservative profile that runs every three to six hours and asks
for no more than 25 results per board. Example terms include:

```text
Flutter Dart Kotlin Android mobile developer fintech payments GraphQL Firebase BLoC
```

Use a Google-specific query when needed, for example:

```text
Flutter developer remote contract Indonesia -intern -unpaid
```

## Board constraints

- Indeed country selection also affects Glassdoor and must use a JobSpy-supported
  country value.
- Google Jobs works best with a complete natural-language search query.
- LinkedIn can rate-limit repeated or high-volume searches; keep result limits
  and cadence conservative.
- Salary, job type, remote, and age filters are not implemented uniformly by
  every board. The plugin validates incompatible combinations before a run.
- A board can return partial data or fail independently. Successful listings
  remain stored and the run records board-level diagnostics.

Always review a listing at its source and apply manually. Do not use this plugin
for login automation, anti-bot bypasses, or automatic proposal submission.

The dashboard shows the latest run state, next scheduled run, per-board counts,
partial failures, ranked reasons, and source links. Jobs can be marked as saved,
dismissed, or applied. A successful alert is sent only once; failed delivery is
recorded and retried on a later qualifying run.