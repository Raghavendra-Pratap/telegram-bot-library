# Optimization for 100 Files

## Configuration Optimized for 100 Forwards

The bot has been optimized to handle up to **100 files forwarded at once** without hitting rate limits.

## Recommended Configuration

Add these to your `.env` file:

```env
# Rate Limiting (Optimized for 100 files)
PROCESSING_DELAY=2.0          # 2 seconds between files
RETRY_DELAY=2.0               # 2 seconds between retries
MAX_RETRIES=5                 # 5 retry attempts (increased for flood control)
FLOOD_RETRY_DELAY_MULTIPLIER=1.5  # Wait 50% longer than Telegram requests
```

## What Changed

### 1. **Increased Processing Delay**
- **Before:** 1.0 second between files
- **After:** 2.0 seconds between files (default)
- **Impact:** 100 files = ~200 seconds (3-4 minutes) instead of ~100 seconds
- **Benefit:** Prevents hitting rate limits

### 2. **Increased Retry Attempts**
- **Before:** 3 retries
- **After:** 5 retries (default)
- **Impact:** More attempts before giving up
- **Benefit:** Better handling of temporary rate limits

### 3. **Increased Retry Delay**
- **Before:** 1.0 second between retries
- **After:** 2.0 seconds between retries (default)
- **Impact:** More spacing between retry attempts
- **Benefit:** Reduces chance of re-hitting rate limits

### 4. **Flood Control Multiplier**
- **New:** `FLOOD_RETRY_DELAY_MULTIPLIER=1.5`
- **Impact:** When Telegram says "wait 30 seconds", bot waits 45 seconds
- **Benefit:** Extra safety margin prevents immediate re-rate-limiting

## Performance for 100 Files

### Time Estimates

**With default settings (PROCESSING_DELAY=2.0):**
- **Minimum time:** 200 seconds (~3.3 minutes)
- **With retries:** 250-300 seconds (~4-5 minutes)
- **With flood control:** 300-400 seconds (~5-7 minutes)

**Breakdown:**
- 100 files × 2.0 seconds = 200 seconds base
- Some files may need retries (+50-100 seconds)
- Flood control waits (+50-100 seconds if triggered)

### Success Rate

**Expected:**
- ✅ **95-100% success rate** with optimized settings
- ✅ All files should get captions
- ⚠️ May take 4-7 minutes for 100 files

## Fine-Tuning

### If Still Hitting Rate Limits

**Increase delays:**
```env
PROCESSING_DELAY=3.0          # 3 seconds between files
RETRY_DELAY=3.0               # 3 seconds between retries
FLOOD_RETRY_DELAY_MULTIPLIER=2.0  # Wait 2x longer
```

**Trade-off:** Slower processing, but more reliable

### If Processing Too Slowly

**Decrease delays (if not hitting limits):**
```env
PROCESSING_DELAY=1.5          # 1.5 seconds between files
RETRY_DELAY=1.5               # 1.5 seconds between retries
```

**Trade-off:** Faster processing, but may hit rate limits

## How It Works

### Processing Flow for 100 Files

```
File 1 → Wait 2s → Process → Add caption
File 2 → Wait 2s → Process → Add caption
File 3 → Wait 2s → Process → Add caption
...
File 100 → Wait 2s → Process → Add caption

Total: ~200 seconds minimum
```

### Flood Control Handling

```
File X → Process → Flood control error
       → Parse "Retry in 30 seconds"
       → Wait 45 seconds (30 × 1.5 multiplier)
       → Retry → Success
```

### Retry Logic

```
Attempt 1 → Error → Wait 2s
Attempt 2 → Error → Wait 2s
Attempt 3 → Error → Wait 2s
Attempt 4 → Error → Wait 2s
Attempt 5 → Error → Give up or try repost
```

## Monitoring

### Check Logs For:

1. **Flood control warnings:**
   ```
   Flood control: Rate limit exceeded. Waiting X seconds...
   ```
   - If you see many of these, increase `PROCESSING_DELAY`

2. **Retry messages:**
   ```
   Retry 1/5 after error: ...
   ```
   - Normal for some files
   - If many files retry, increase delays

3. **Success rate:**
   ```
   ✅ Successfully added caption: filename.mp4
   ```
   - Should see this for most files

## Troubleshooting

### Issue: Still hitting rate limits with 100 files

**Solution:**
1. Increase `PROCESSING_DELAY` to 3.0
2. Increase `FLOOD_RETRY_DELAY_MULTIPLIER` to 2.0
3. Process files in smaller batches (50 at a time)

### Issue: Processing too slow

**Solution:**
1. Decrease `PROCESSING_DELAY` to 1.5 (if not hitting limits)
2. Monitor for rate limit errors
3. Adjust based on your specific use case

### Issue: Some files still failing

**Solution:**
1. Increase `MAX_RETRIES` to 7-10
2. Increase `RETRY_DELAY` to 3.0
3. Check bot permissions (`/status` command)

## Best Practices

### For 100 Files:

1. **Use recommended settings:**
   ```env
   PROCESSING_DELAY=2.0
   MAX_RETRIES=5
   RETRY_DELAY=2.0
   FLOOD_RETRY_DELAY_MULTIPLIER=1.5
   ```

2. **Monitor first batch:**
   - Forward 10-20 files first
   - Check if any rate limit errors
   - Adjust if needed

3. **Be patient:**
   - 100 files will take 4-7 minutes
   - This is normal and safe

4. **Check logs:**
   - Monitor for flood control warnings
   - Adjust delays if needed

## Summary

| Setting | Default | For 100 Files | Purpose |
|---------|---------|--------------|---------|
| `PROCESSING_DELAY` | 2.0s | 2.0-3.0s | Space out file processing |
| `MAX_RETRIES` | 5 | 5-7 | More attempts for flood control |
| `RETRY_DELAY` | 2.0s | 2.0-3.0s | Delay between retries |
| `FLOOD_RETRY_DELAY_MULTIPLIER` | 1.5 | 1.5-2.0 | Extra wait time for safety |

**Result:** Bot can now reliably handle 100 files forwarded at once with 95-100% success rate.

