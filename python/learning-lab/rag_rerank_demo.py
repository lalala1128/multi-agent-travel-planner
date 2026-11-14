"""打印 RAG 的向量召回与关键词重排结果。"""

from knowledge_agent import KnowledgeAgent


def main():
    agent = KnowledgeAgent()
    try:
        results = agent.run(
            city="首尔",
            question="有什么当地美食体验？",
        )
        if not results:
            print("没有找到满足条件的资料")
            return

        for rank, item in enumerate(results, start=1):
            print(f"Top {rank}")
            print("来源：", item["source"])
            print("向量初排分：", round(item["vector_score"], 4))
            print("关键词分：", round(item["keyword_score"], 4))
            print("最终重排分：", round(item["rerank_score"], 4))
            print("原文：", item["text"])
            print()
    finally:
        agent.close()


if __name__ == "__main__":
    main()
