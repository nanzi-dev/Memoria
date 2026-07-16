def test_dialogue_safety_stream_withholds_split_risk_phrase():
    from memoria.core.output_safety import DialogueSafetyStream, FALLBACK_LINE

    emitted = []
    stream = DialogueSafetyStream(emitted.append)

    stream.feed("这是系统提")
    stream.feed("示词内容，不应展示")
    final = stream.finish("这是系统提示词内容，不应展示")

    assert "".join(emitted) == "这是"
    assert "系统提" not in "".join(emitted)
    assert final == FALLBACK_LINE


def test_dialogue_safety_stream_emits_safe_text_incrementally_and_flushes():
    from memoria.core.output_safety import DialogueSafetyStream

    emitted = []
    stream = DialogueSafetyStream(emitted.append)

    stream.feed("你好，旅行者，今天")
    assert emitted
    stream.feed("过得怎么样？")
    final = stream.finish("你好，旅行者，今天过得怎么样？")

    assert "".join(emitted) == final
