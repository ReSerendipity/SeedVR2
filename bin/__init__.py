"""``bin`` 包标记。

全项目统一以 ``from bin.integrated_app...`` 形式导入应用层代码，因此 ``bin``
应当是一个明确的常规包，而非 PEP 420 命名空间包。补齐此文件可消除 mypy 在
``explicit_package_bases`` 下将同一模块同时解析为 ``integrated_app.*`` 与
``bin.integrated_app.*`` 两个名字的歧义（"Source file found twice"）。
"""
