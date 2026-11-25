from protocol.messages import MessageType, decode, encode, make


def test_roundtrip():
    msg = make(MessageType.REGISTER, worker_id="w1", cores=4, consented=True)
    raw = encode(msg)
    assert raw.endswith(b"\n")
    back = decode(raw)
    assert back["type"] == "REGISTER"
    assert back["worker_id"] == "w1"
    assert back["consented"] is True


def test_decode_empty():
    assert decode("\n") is None
    assert decode(b"") is None
