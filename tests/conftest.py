"""pytest 配置：忽略脚本式测试文件(它们是 __main__ 脚本，不是 pytest 用例)。

test_batch_4stocks.py / test_verify_4fixes.py 的 test_stock 函数带 (orch, code, name, stock_type)
参数，是脚本式调用(main 里手动构造 orch 传入)，pytest 收集会报 'orch' fixture not found。
这两个文件应通过 `python tests/test_batch_4stocks.py` 手动运行，不是 pytest。
"""
collect_ignore = ["test_batch_4stocks.py", "test_verify_4fixes.py"]
