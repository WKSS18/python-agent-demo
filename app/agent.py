import base64
from collections.abc import Callable
from typing import Any, TypedDict

from anthropic import Anthropic
from langgraph.graph import END, StateGraph

from app import schemas
from app.config import get_settings


SYSTEM_PROMPT = (
    "你是一个学习用 AI Agent。如果提供了 notes 上下文，应优先根据笔记回答；"
    "如果没有匹配的 notes，则直接根据模型自身知识回答。"
    "不得声称引用了未提供的笔记，也不得编造引用来源。回答要简洁、务实。"
)


class AgentState(TypedDict):
    question: str
    owner_id: int
    context: str
    used_notes: list[schemas.NoteRead]
    answer: str


def retrieve_notes(
    state: AgentState,
    retrieve: Callable[[int, str], list[schemas.NoteRead]],
) -> AgentState:
    used_notes = retrieve(state["owner_id"], state["question"])
    context = "\n\n".join(
        f"标题：{note.title}\n内容：{note.content}"
        for note in used_notes
    )
    return {**state, "context": context, "used_notes": used_notes}


def generate_answer(state: AgentState) -> AgentState:
    answer = "".join(stream_answer(state["question"], state["used_notes"]))
    return {**state, "answer": answer}


def stream_answer(question: str, used_notes: list[schemas.NoteRead]):
    """逐段产出模型文本；Service 决定如何传输和持久化这些文本。"""
    context = "\n\n".join(
        f"标题：{note.title}\n内容：{note.content}"
        for note in used_notes
    )

    user_content = (
        f"问题：{question}\n\n"
        f"notes 上下文：\n{context or '（没有检索到相关笔记，请使用模型自身知识回答）'}"
    )
    yield from _stream_model(SYSTEM_PROMPT, user_content)


def stream_file_analysis(
    filename: str,
    extracted_text: str,
    question: str,
    extraction_method: str,
    image_content: bytes | None = None,
    image_media_type: str | None = None,
):
    """图片优先交给视觉模型，文档则分析服务端提取的文本。"""
    system_prompt = (
        "你是严谨的多模态文件分析助手。只能基于用户提供的图片或提取文本回答，不要编造。"
        "对图片要分析主体、场景、构图、可见文字和整体含义；不确定的内容要明确标注。"
        "对文档先给出摘要，再列出关键信息、风险或疑点以及可执行建议。"
        "如果文本来自 OCR，要提醒用户可能存在识别误差。回答使用中文，结构清晰、务实。"
    )
    text_prompt = (
        f"文件名：{filename}\n"
        f"提取方式：{extraction_method}\n"
        f"分析要求：{question}\n\n"
        f"OCR/提取文本：\n{extracted_text or '（未识别到文字，请直接根据图片分析）'}"
    )
    user_content: str | list[dict[str, Any]] = text_prompt
    settings = get_settings()
    if settings.anthropic_vision_enabled and image_content and image_media_type:
        # Anthropic 官方建议先放图片再放问题文本。
        user_content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image_media_type,
                    "data": base64.b64encode(image_content).decode("ascii"),
                },
            },
            {"type": "text", "text": text_prompt},
        ]
    vision_model = settings.anthropic_vision_model or None
    yield from _stream_model(system_prompt, user_content, model=vision_model)


def _stream_model(
    system_prompt: str,
    user_content: str | list[dict[str, Any]],
    model: str | None = None,
):
    settings = get_settings()
    if not settings.anthropic_auth_token:
        has_image = isinstance(user_content, list)
        input_kind = "图片" if has_image else "输入文本"
        mock_answer = (
            "这是本地 mock Agent 回复。\n\n"
            f"已收到{input_kind}；配置支持视觉的模型密钥后，"
            "会在这里返回真实的流式分析结果。"
        )
        # mock 也分块返回，前端无需为开发环境维护另一套逻辑。
        for index in range(0, len(mock_answer), 12):
            yield mock_answer[index:index + 12]
        return

    client = Anthropic(
        api_key=settings.anthropic_auth_token,
        base_url=settings.anthropic_base_url,
        timeout=settings.api_timeout_ms / 1000,
    )
    with client.messages.stream(
        model=model or settings.anthropic_model,
        max_tokens=2_048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    ) as stream:
        yield from stream.text_stream


def run_agent(
    owner_id: int,
    question: str,
    note_retriever: Callable[[int, str], list[schemas.NoteRead]],
) -> tuple[str, list[schemas.NoteRead]]:
    # 用 LangGraph 表达 Agent 编排：检索上下文 -> 模型生成。
    workflow = StateGraph(AgentState)
    workflow.add_node("retrieve_notes", lambda state: retrieve_notes(state, note_retriever))
    workflow.add_node("generate_answer", generate_answer)
    workflow.set_entry_point("retrieve_notes")
    workflow.add_edge("retrieve_notes", "generate_answer")
    workflow.add_edge("generate_answer", END)

    app = workflow.compile()
    result = app.invoke(
        {
            "question": question,
            "owner_id": owner_id,
            "context": "",
            "used_notes": [],
            "answer": "",
        },
    )
    return result["answer"], result["used_notes"]
