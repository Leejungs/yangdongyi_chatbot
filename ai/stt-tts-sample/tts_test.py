import asyncio, edge_tts

VOICE = "ko-KR-SunHiNeural"  # 안되면 'ko-KR-YunJaeNeural'로 바꿔보기
TEXT = "안녕하세요. 샘플 TTS 입니다."

async def main():
    c = edge_tts.Communicate(text=TEXT, voice=VOICE)
    chunks = []
    async for ch in c.stream():
        if ch["type"] == "audio":
            chunks.append(ch["data"])
    data = b"".join(chunks)
    print("audio bytes:", len(data))
    open("direct_test.mp3","wb").write(data)

asyncio.run(main())