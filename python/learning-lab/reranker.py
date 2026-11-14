"""向量召回后的轻量关键词重排，不依赖额外模型。"""

import re


def extract_keywords(text: str) -> set[str]:
    normalized = text.lower()
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", normalized))
    tokens = set(re.findall(r"[a-z0-9]+", normalized))
    tokens.update(chinese)
    tokens.update(chinese[index:index + 2] for index in range(len(chinese) - 1))
    return tokens


def keyword_score(question: str, text: str) -> float:
    question_terms = extract_keywords(question)
    if not question_terms:
        return 0.0
    return len(question_terms & extract_keywords(text)) / len(question_terms)


def rerank(
    question: str,
    candidates: list[dict],
    keyword_weight: float = 0.2,
) -> list[dict]:
    """以向量分数为主、关键词命中为辅，对候选片段二阶段排序。"""
    if not 0 <= keyword_weight <= 1:
        raise ValueError("keyword_weight 必须在 0 到 1 之间")

    ranked = []
    for candidate in candidates:
        vector_score = float(candidate["score"])
        lexical_score = keyword_score(question, candidate["text"])
        final_score = (
            (1 - keyword_weight) * vector_score
            + keyword_weight * lexical_score
        )
        ranked.append({
            **candidate,
            "vector_score": vector_score,
            "keyword_score": lexical_score,
            "rerank_score": final_score,
            "score": final_score,
        })

    return sorted(ranked, key=lambda item: item["rerank_score"], reverse=True)
