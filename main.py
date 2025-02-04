import asyncio
from dotenv import load_dotenv
from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli, llm
from livekit.agents.voice_assistant import VoiceAssistant
from livekit.plugins import openai, silero
from functions import AssistantFnc
from datetime import date

load_dotenv()       # loading .env file

current_date = date.today().strftime("%B %d, %Y")   # getting current date of when using this app



async def entrypoint(ctx: JobContext):          # initializing main function to run asynchronously
    
    # giving the assistant initial instructions to control behaviour
    initial_ctx = llm.ChatContext().append(
        role="system",
        text=(
            f"You are a voice assistant created by LiveKit. Your interface with users will be voice. Today is {current_date} "
            "You should use short and concise responses, and avoiding usage of unpronouncable punctuation."
            "After the speaker ended with speaking, start immediately executing its commands"
        ),
    )

    # connecting to job context and audio
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    fnc_ctx = AssistantFnc()

    # assistant components
    assitant = VoiceAssistant(
        vad=silero.VAD.load(),
        stt=openai.STT(),           # speech-to-text
        llm=openai.LLM(),           # llm model
        tts=openai.TTS(),           # text-to-speech
        chat_ctx=initial_ctx,
        fnc_ctx=fnc_ctx,
    )
    
    # starting assistant
    assitant.start(ctx.room)        

    # 
    await asyncio.sleep(2)
    await assitant.say("Hey, how can I help you today!", allow_interruptions=True)


# running the application
if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))