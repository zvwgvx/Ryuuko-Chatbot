#!/usr/bin/env python3
# coding: utf-8
# queue.py - Request queue system with owner priority handling

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional, Dict, Set
import discord

logger = logging.getLogger("Request Queue")

@dataclass
class QueuedRequest:
    """Represent a queued AI request"""
    message: discord.Message
    user_id: int
    is_owner: bool
    timestamp: float
    final_user_text: str
    
    def __lt__(self, other):
        # Owner requests have higher priority (lower number = higher priority)
        # If same priority level, earlier timestamp wins
        if self.is_owner != other.is_owner:
            return self.is_owner  # True < False, so owner goes first
        return self.timestamp < other.timestamp

class RequestQueue:
    """Request queue system for AI processing with owner priority"""
    
    def __init__(self):
        self._queue = None  # Will be lazy initialized when needed
        self._processing_users: Set[int] = set()
        self._user_last_request: Dict[int, float] = {}  # Rate limiting
        self._is_processing = False
        self._worker_task: Optional[asyncio.Task] = None
        
        # Callbacks
        self._process_callback = None
        self._bot = None
    
    def _ensure_queue_initialized(self):
        """Lazy initialization của queue để tránh event loop issues"""
        if self._queue is None:
            try:
                self._queue = asyncio.PriorityQueue()
            except RuntimeError:
                # Nếu chưa có event loop, thử tạo một cái mới
                loop = asyncio.get_event_loop()
                self._queue = asyncio.PriorityQueue()
    
    def set_bot(self, bot):
        """Set bot instance for owner checking"""
        self._bot = bot
    
    def set_process_callback(self, callback):
        """Set callback function to process requests"""
        self._process_callback = callback
    
    async def is_owner(self, user: discord.abc.User) -> bool:
        """Check if user is bot owner"""
        if self._bot is None:
            return False
        try:
            return await self._bot.is_owner(user)
        except Exception:
            return False
    
    # Replace the add_request method in queue.py

    # Replace the add_request method in queue.py with this fixed version:

    async def add_request(self, message: discord.Message, final_user_text: str) -> tuple[bool, str]:
        """
        Add a request to queue - FIXED VERSION
        Returns: (success: bool, message: str)
        """
        self._ensure_queue_initialized()
        
        user_id = message.author.id
        current_time = time.time()
        
        # Check if user already has a request being processed
        if user_id in self._processing_users:
            return False, "⏳ You have a request being processed. Please wait for it to complete."
        
        # Check if user already has requests in queue - IMPROVED CHECK
        user_has_queued_request = False
        temp_queue_items = []
        
        # Drain the queue to check for existing user requests
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
                temp_queue_items.append(item)
                if item.user_id == user_id:
                    user_has_queued_request = True
            except asyncio.QueueEmpty:
                break
        
        # Put all items back in the queue
        for item in temp_queue_items:
            await self._queue.put(item)
        
        if user_has_queued_request:
            return False, "⏳ You already have a request in queue. Please wait."
        
        # Rate limiting (except for owner)
        is_owner = await self.is_owner(message.author)
        if not is_owner:
            last_request = self._user_last_request.get(user_id, 0)
            if current_time - last_request < 3.0:  # Reduced to 3 seconds for faster testing
                remaining = 3.0 - (current_time - last_request)
                return False, f"⏰ Please wait {remaining:.1f}s before sending another request."
        
        # Create request with EXACT text from the current message
        request = QueuedRequest(
            message=message,
            user_id=user_id,
            is_owner=is_owner,
            timestamp=current_time,
            final_user_text=final_user_text  # Make sure this is the CURRENT request text
        )
        
        # Log the request being added
        logger.info(f"Adding request to queue for user {user_id}: {final_user_text[:100]}")
        
        # Add to queue
        await self._queue.put(request)
        self._user_last_request[user_id] = current_time
        
        # Start worker if not running
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())
        
        return True, None
    async def _worker(self):
        """Background worker to process queued requests"""
        logger.info("Request queue worker started")
        
        while True:
            try:
                # Đảm bảo queue được khởi tạo
                self._ensure_queue_initialized()
                
                # Get next request (this will block until available)
                request = await self._queue.get()
                
                # Mark user as being processed
                self._processing_users.add(request.user_id)
                
                try:
                    # Process the request
                    if self._process_callback:
                        await self._process_callback(request)
                    
                except Exception as e:
                    logger.exception(f"Error processing request for user {request.user_id}")
                    try:
                        await request.message.channel.send(
                            f"❌ Lỗi khi xử lý request: {e}",
                            reference=request.message,
                            allowed_mentions=discord.AllowedMentions.none()
                        )
                    except Exception:
                        logger.exception("Failed to send error message")
                
                finally:
                    # Always remove user from processing set
                    self._processing_users.discard(request.user_id)
                    self._queue.task_done()
                
            except asyncio.CancelledError:
                logger.info("Request queue worker cancelled")
                break
            except Exception:
                logger.exception("Unexpected error in request queue worker")
                await asyncio.sleep(1)  # Prevent tight loop on persistent errors
    
    async def stop(self):
        """Stop the queue worker"""
        logger.info("Stopping request queue...")
        
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                logger.info("Worker task cancelled successfully")
        
        # Clear processing users
        self._processing_users.clear()
        
        # Clear remaining queue items if any
        if self._queue is not None:
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                except asyncio.QueueEmpty:
                    break
        
        logger.info("Request queue stopped")

# Singleton instance
_request_queue = None

def get_request_queue() -> RequestQueue:
    """Get singleton instance of RequestQueue"""
    global _request_queue
    if _request_queue is None:
        _request_queue = RequestQueue()
    return _request_queue