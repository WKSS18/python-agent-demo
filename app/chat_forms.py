"""聊天内结构化业务动作的白名单匹配器。

模型文本不能直接决定要调用哪个内部接口。本模块只允许服务端明确实现的动作，
前端再按 ``kind`` 映射到受控组件，以降低提示词注入和越权调用风险。
"""

from typing import Any


NOTE_FORM_ACTIONS = ("创建", "新建", "添加", "记一条")


def match_form(question: str) -> dict[str, Any] | None:
    """只返回服务端白名单内的表单，避免模型构造任意接口调用。"""
    normalized = question.replace(" ", "")
    if "笔记" not in normalized or not any(action in normalized for action in NOTE_FORM_ACTIONS):
        return None

    return {
        "kind": "note_create",
        "status": "pending",
        "title": "创建知识笔记",
        "description": "填写后会保存到当前账户的 Notes，并可用于后续 Agent 检索。",
        "submit_label": "创建笔记",
        "fields": [
            {
                "name": "title",
                "label": "标题",
                "type": "text",
                "placeholder": "例如：SSE 学习笔记",
                "required": True,
                "max_length": 200,
            },
            {
                "name": "content",
                "label": "内容",
                "type": "textarea",
                "placeholder": "记录关键知识或待办事项",
                "required": True,
            },
        ],
    }
