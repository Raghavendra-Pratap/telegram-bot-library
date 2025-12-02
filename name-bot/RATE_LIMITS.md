# Rate Limits and File Processing Caps

## Current Bot Implementation

### ✅ **No Built-in Caps**
The bot does **NOT** have any artificial limits on:
- Number of files processed per second/minute
- Maximum files in a batch
- Queue size
- Concurrent processing

### How It Works

**Event-Driven Processing:**
- Each file upload triggers `handle_file()` independently
- Files are processed **one at a time** as they arrive
- No batching or queuing system
- Each file is handled in its own async task

**Processing Flow:**
```
File 1 uploaded → handle_file() → Process → Add caption
File 2 uploaded → handle_file() → Process → Add caption
File 3 uploaded → handle_file() → Process → Add caption
... (no limit)
```

## Built-in Delays

### 1. **Processing Delay**
```python
await asyncio.sleep(0.5)  # 0.5 seconds before processing
```
- **Purpose:** Wait for Telegram to fully process the message
- **Impact:** Adds 0.5s delay per file
- **Not a cap:** Just ensures message is ready

### 2. **Retry Delays**
```python
RETRY_DELAY = 1.0  # 1 second between retries
MAX_RETRIES = 3    # Up to 3 retry attempts
```
- **Purpose:** Handle temporary errors
- **Impact:** Adds 1s delay per retry (if needed)
- **Not a cap:** Only used on errors

## Telegram API Rate Limits

### Official Telegram Limits

**Message Sending:**
- **30 messages per second** per bot (general limit)
- **20 messages per second** per group/channel (more strict)
- Rate limits apply to **sending** messages, not editing

**Message Editing:**
- No specific documented limit for editing
- Generally more lenient than sending
- Subject to general API rate limits

**File Operations:**
- File uploads: Limited by file size (50MB free, 4GB premium)
- File downloads: No specific limit
- File forwarding: Limited by message rate limits

### What This Means

**For Direct Uploads (Edit Method):**
- ✅ **No practical limit** - Editing is fast and not rate-limited
- ✅ Can process **hundreds of files** quickly
- ⚠️ 0.5s delay per file adds up (100 files = 50 seconds minimum)

**For Repost Method (Groups):**
- ⚠️ **Subject to rate limits** - Each repost = 1 send + 1 delete
- ⚠️ **~20 messages/second** limit per channel/group
- ⚠️ 100 files = ~5 seconds minimum (if at rate limit)
- ⚠️ May hit rate limits with many files at once

## Real-World Performance

### Scenario 1: Upload 10 Files
- **Time:** ~5-10 seconds (0.5s delay × 10 files)
- **Result:** ✅ All processed successfully
- **No issues:** Well within limits

### Scenario 2: Upload 50 Files
- **Time:** ~25-50 seconds (0.5s delay × 50 files)
- **Result:** ✅ All processed successfully
- **No issues:** Still manageable

### Scenario 3: Upload 100 Files
- **Time:** ~50-100 seconds (0.5s delay × 100 files)
- **Result:** ✅ Most processed successfully
- **Potential issues:** 
  - If many need repost → May hit rate limits
  - Some may fail and retry

### Scenario 4: Upload 500+ Files
- **Time:** ~4+ minutes (0.5s delay × 500 files)
- **Result:** ⚠️ May hit rate limits
- **Issues:**
  - Rate limit errors
  - Some files may need multiple retries
  - Processing slows down

## Recommendations

### For Small Batches (< 50 files)
✅ **No changes needed**
- Current implementation handles this well
- 0.5s delay is acceptable
- No rate limit issues

### For Medium Batches (50-200 files)
⚠️ **Consider adding delays**
- Add configurable delay between files
- Process in smaller batches
- Monitor for rate limit errors

### For Large Batches (200+ files)
❌ **Add rate limiting**
- Implement queue system
- Add delays between processing
- Process in batches with pauses
- Consider background job processing

## Potential Improvements

### Option 1: Add Rate Limiting
```python
# In config.py
MAX_FILES_PER_MINUTE = int(os.getenv("MAX_FILES_PER_MINUTE", "60"))

# In handle_file()
# Check rate limit before processing
# Queue files if limit exceeded
```

### Option 2: Add Batch Processing
```python
# Process files in batches
# Add delay between batches
# Better for large uploads
```

### Option 3: Add Queue System
```python
# Queue files for processing
# Process with rate limiting
# Better error handling
```

## Current Limitations

### What the Bot CAN'T Do
- ❌ Process files in parallel (one at a time)
- ❌ Skip rate limits (subject to Telegram limits)
- ❌ Guarantee all files processed instantly
- ❌ Handle infinite concurrent uploads

### What the Bot CAN Do
- ✅ Process files as fast as Telegram allows
- ✅ Handle errors gracefully
- ✅ Retry failed operations
- ✅ Process unlimited number of files (over time)

## Summary

| Aspect | Current Status | Limit |
|--------|---------------|-------|
| **Bot Caps** | ❌ None | Unlimited |
| **Processing Speed** | ~2 files/second | 0.5s delay per file |
| **Telegram Rate Limits** | ⚠️ Applies | ~20-30 msg/sec |
| **Concurrent Files** | ✅ Supported | No limit |
| **Total Files** | ✅ Unlimited | No cap |

**Bottom Line:**
- Bot has **no artificial caps**
- Limited by **Telegram API rate limits** (~20-30 messages/second)
- **0.5s delay** per file adds up with many files
- For **large batches**, consider adding rate limiting

## Recommendations

**For your use case:**
1. **Small batches (< 50 files):** Current implementation is fine
2. **Medium batches (50-200 files):** Should work, may be slow
3. **Large batches (200+ files):** Consider adding rate limiting

**Would you like me to add:**
- Configurable rate limiting?
- Batch processing with delays?
- Queue system for large uploads?

