"""GPU Monitor internals: sampling, metric registry, and the ia-usage card.

Deliberately empty of imports. `prefs` needs `app_template` on sys.path,
which only the entry point arranges; re-exporting it here would make even
`from monitor.sampler import query_gpu` fail outside the app.
"""
