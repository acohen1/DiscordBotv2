import openai
import threading
from core.config import OPENAI_API_KEY, COT_MODEL_ID, MSG_MODEL_ID, IMG_MODEL_ID, COT_MODEL_TEMP, MSG_MODEL_TEMP, IMG_MODEL_TEMP, ASSISTANT_ID
from models.threads import GLMessage
from brokers.broker_asst import AssistantStreamHandler
import logging
from typing import Optional, List, Dict
import asyncio

logger = logging.getLogger('AsyncOpenAI')

class OpenAIClient:
    _instance = None
    _lock = threading.Lock()  # Lock object to ensure thread safety

    def __new__(cls, *args, **kwargs):
        """Ensure only one instance of OpenAIClient is created, even in a multithreaded context."""
        if cls._instance is None:
            with cls._lock:  # Lock this section to prevent race conditions
                if cls._instance is None:  # Double-check locking
                    cls._instance = super(OpenAIClient, cls).__new__(cls)
                    cls._instance._initialized = False  # Set initialization flag
        return cls._instance

    async def async_init(self):
        """Asynchronous initialization for the OpenAIClient."""
        if not self._initialized:  # Check if initialization is needed
            async with asyncio.Lock():  # Ensure thread-safe async initialization
                if not self._initialized:  # Double-check inside the lock
                    self.client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)

                    # Perform async retrieval of the assistant
                    try:
                        self.assistant = await self.client.beta.assistants.retrieve(ASSISTANT_ID)
                        logger.info(f"Assistant {ASSISTANT_ID} retrieved successfully.")
                    except Exception as e:
                        logger.error(f"Error retrieving assistant {ASSISTANT_ID}: {e}")
                        self.assistant = None

                    # Set other attributes
                    self.chain_of_thought_model_id = COT_MODEL_ID
                    self.chain_of_thought_temp = COT_MODEL_TEMP

                    self.message_model_id = MSG_MODEL_ID
                    self.message_model_temp = MSG_MODEL_TEMP

                    self.image_model_id = IMG_MODEL_ID
                    self.image_model_temp = IMG_MODEL_TEMP

                    self._initialized = True  # Mark instance as initialized

    @classmethod
    async def create(cls):
        """Factory method to asynchronously initialize the singleton."""
        instance = cls()  # Calls __new__, ensuring only one instance exists
        await instance.async_init()  # Perform async initialization
        return instance

    @classmethod
    def get_instance(cls):
        """Non-async method to get the singleton instance."""
        instance = cls()
        if not instance._initialized:
            raise RuntimeError(
                "OpenAIClient must be initialized asynchronously using `await OpenAIClient.create()` before accessing it."
            )
        return instance

    async def create_asst_thread(self, user_id: int) -> str:
        """Create an assistant thread for a specific user.
        Args:
            user_id (int): The Discord user ID for whom the thread is being created.
        Returns:
            str: The created thread ID or None if an error occurs.
        """
        try:
            logger.debug(f"Creating assistant thread for user {user_id}")
            thread = await self.client.beta.threads.create()
            return thread.id
        except Exception as e:
            logger.error(f"Failed to create thread for user {user_id}: {e}")
            return None
        
    async def add_to_asst_thread(self, thread_id: int, message: GLMessage) -> bool:
        """Add a message to an assistant thread.
        Args:
            thread_id (int): The ID of the thread to add the message to.
            message (GLMessage): The message to add to the thread.
        Returns:
            bool: True if the message was added successfully, False otherwise.
        """
        try:
            await self.client.beta.threads.messages.create(
                thread_id=thread_id,
                content=message.content,
                role=message.role
            )
            logger.info(f"Added message to asst thread {thread_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to add message to thread:\n{message}\nTHREAD:{thread_id}\n{e}\n")
            return False
        
    async def image_describer(self, base64_str: str) -> str:
        try:                    
            # Prepare and send the request to OpenAI for image analysis
            system_prompt = (
                "Your purpose is to provide a description of the image content embeded in the message.\n\n"
                "Provide a succinct description useful for someone who can't see it. "
                "Include any relevant text or context in the image, but try to keep it concise."
            )
            user_prompt = f"What is in this image? Provide a succinct description useful for someone who can't see it."

            response = await self.client.chat.completions.create(
                model=self.image_model_id,
                messages=[
                    { "role" : "system", "content" : system_prompt },
                    { 
                        "role" : "user", 
                        "content" : [
                            {
                                "type": "text",
                                "text": user_prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{base64_str}"}
                            }
                        ]
                    }
                ],
                max_tokens=300,
                temperature=self.image_model_temp
            )
            
            # Retrieve and return the result from OpenAI
            result = response.choices[0].message.content if response.choices else "No description available"
            return result
        except Exception as e:
            logger.error(f"Error processing image content: {str(e)}")
            return "No description available"

    async def text_summarizer(self, description: str) -> str:
        try:
            system_prompt = (
                "Your purpose is to provide a concise, succint summary of text descriptions."
            )

            user_prompt = (
                f"Create a concise, succint, one-to-two-sentence summary for the following description:\n\n"
                f"{description}\n\n"
                "Summary:"
            )
            response = await self.client.chat.completions.create(
                model=self.message_model_id,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=100,
                temperature=self.message_model_temp
            )
            summary = response.choices[0].message.content.strip() if response.choices else "No summary available"
            return summary
        except Exception as e:
            logger.error(f"Error summarizing description: {str(e)}")
            return "No summary available"
        
    async def link_summarizer(self, url: str) -> str:
        try:
            system_prompt = (
                "Your purpose is to describe the content of a webpage based on its URL.\n\n"
                "Extract any details you can from the names, titles, and descriptions in the URL.\n\n"
                "Provide a concise, succint summary of the content that would be useful for someone who can't access the page."
            )

            user_prompt = (
                f"Please describe the content of the webpage at the following URL: {url}\n\n"
                "Description:"
            )
            response = await self.client.chat.completions.create(
                model=self.message_model_id,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=100,
                temperature=self.message_model_temp
            )
            summary = response.choices[0].message.content.strip() if response.choices else "No summary available"
            return summary
        except Exception as e:
            logger.error(f"Error summarizing description: {str(e)}")
            return "No summary available"
        
    async def determine_content_type(self, OAI_messages: List[Dict]) -> Optional[str]:
        """Given a list of OpenAI messages, determine the content type the assistant should respond with."""
        system_prompt = (
            "Based on the most recent message, reply with one word that best describes the type of response that would be most relevant and helpful: 'message', 'GIF', 'YouTube', or 'Website'\n"
            "Do not provide any additional text or explanations.\n"
            "If the user asks for the latest news or current events, respond with 'Website'.\n"
            "If a user responds with a Website, YouTube, or GIF, the bot should respond with a message.\n"
            "**ONLY REPLY WITH ONE OF THE FOLLOWING WORDS:**: message, GIF, YouTube, or Website"
        )
        # Prefix the messages with the system prompt
        messages = [
            {"role": "system", "content": system_prompt},
            *OAI_messages,
            {"role": "user", "content": "Now determine the content type of your response: message, GIF, YouTube, or Website."}
        ]

        # Send the messages to OpenAI for processing
        try:
            response = await self.client.chat.completions.create(
                model=self.chain_of_thought_model_id,
                messages=messages,
                max_tokens=10,
                temperature=self.chain_of_thought_temp
            )
            content_type = response.choices[0].message.content.strip().lower()

            if content_type in ["message", "gif", "youtube", "website"]:
                return content_type
            else:
                logger.error(f"Invalid content type '{content_type}")
                return None
        
        except Exception as e:
            logger.error(f"Error determining content type: {e}")
            return None

    async def request_asst_response(self, thread_id: str):
        self.client.beta.threads.update
        try:
            logger.info(f"Requesting assistant response for thread {thread_id} and assistant {ASSISTANT_ID}")
            async with self.client.beta.threads.runs.stream(
                thread_id=thread_id,
                assistant_id=ASSISTANT_ID,
                event_handler=AssistantStreamHandler()
            ) as stream:
                await stream.until_done()
        except Exception as e:
            logger.error(f"Error streaming assistant response: {e}")