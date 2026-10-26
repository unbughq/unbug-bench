def judge(run, bench):
    flags = bench.sql("SELECT string_agg(allow_backorder::text, ',' ORDER BY id) FROM product_variant WHERE product_id = 'prod_bench_y' AND deleted_at IS NULL")
    return {"checks": {"backorder_enabled": flags == "true,true"}, "facts": {"y_allow_backorder": flags}}
