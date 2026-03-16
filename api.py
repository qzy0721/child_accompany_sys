# api.py

from dashscope import Generation
from http import HTTPStatus
from config import Qwen_MODEL


def call_qwen_stream(messages):
    """
    调用 Qwen-Turbo 流式接口，返回生成内容流
    :param messages: 消息列表，格式为 [{"role": "user", "content": "..."}]
    :return: yield 每个流式返回的文本片段
    """
    responses = Generation.call(
        model=Qwen_MODEL,
        messages=messages,
        result_format="message",
        stream=True,
        incremental_output=True
    )

    for response in responses:
        if response.status_code == HTTPStatus.OK:
            content = response.output.choices[0]["message"]["content"]
            yield content
        else:
            yield f"\n[ERROR] {response.code}: {response.message}"