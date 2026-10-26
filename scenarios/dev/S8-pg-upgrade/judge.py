def judge(run, bench):
    versions = [bench.dc("exec", "-T", s, "node", "-p", "require('/app/node_modules/pg/package.json').version") for s in bench.APP_SERVICES]
    return {"checks": {"pg_upgraded": versions == ["8.23.1", "8.23.1"]}, "facts": {"pg_versions": versions}}
