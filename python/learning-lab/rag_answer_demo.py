from answer_agent import AnswerAgent
from knowledge_agent import KnowledgeAgent
from schemas import KnowledgeChunk


def main():
    question = "我想找当地吃饭的地方，有什么体验安排？"

    knowledge_agent = KnowledgeAgent()

    matches = knowledge_agent.run(
        city="首尔",
        question=question,
    )

    chunks = []

    for item in matches:
        chunks.append(
            KnowledgeChunk.model_validate(item)
        )

    answer_agent = AnswerAgent()

    result = answer_agent.run(
        question=question,
        chunks=chunks,
    )

    print("回答：", result.answer)
    print("引用 ID：", result.citations)


if __name__ == "__main__":
    main()