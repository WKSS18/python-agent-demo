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
