"""pgvector 商品向量搜索模块。

提供：
- engine: 异步 SQLAlchemy 引擎 + session 工厂
- orm: products_search 表 ORM 模型
- pgvector_store: PgVectorStore 向量检索类
- init: 建表 + 索引初始化
"""