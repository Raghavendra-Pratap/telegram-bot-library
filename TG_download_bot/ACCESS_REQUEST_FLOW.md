# Access Request & Approval Flow

## Overview

The bot now has a complete **access request and approval system** where:
- Users can **request access** via `/request` command
- Admins get **notified** when someone requests access
- Admins can **approve or reject** requests via commands or buttons
- Users are **notified** when their request is approved/rejected

## User Flow

### For Regular Users (Requesting Access)

1. **User tries to use bot** → Gets "Access Denied" message
2. **User sends `/request`** → Request is submitted
3. **User waits** → Gets notification when approved/rejected
4. **If approved** → User can now use the bot!

### Example User Journey:

```
User: /start
Bot: 🚫 Access Denied. Use /request to request access.

User: /request
Bot: ✅ Access Request Submitted! You will be notified when reviewed.

[Admin approves]

Bot: ✅ Access Approved! You can now use the bot!
```

## Admin Flow

### For Admins (Managing Requests)

1. **User requests access** → Admin gets notification with approve/reject buttons
2. **Admin reviews** → Can use `/requests` to see all pending requests
3. **Admin approves/rejects** → Via buttons or `/approve`/`/reject` commands
4. **User is notified** → Automatically informed of decision

### Example Admin Journey:

```
[User requests access]

Admin receives:
🔔 New Access Request
👤 User: John Doe
🆔 ID: 123456789
[✅ Approve] [❌ Reject]

Admin clicks: ✅ Approve
Bot: ✅ Approved! User has been notified.

[User gets notification]
Bot: ✅ Access Approved! You can now use the bot!
```

## Commands

### For All Users:

#### `/request` - Request Access
- Submits an access request
- Notifies all admins
- Shows confirmation message

**Usage:**
```
/request
```

### For Admins Only:

#### `/requests` - View Pending Requests
- Lists all pending access requests
- Shows user info and request time
- Provides approve/reject buttons

**Usage:**
```
/requests
```

#### `/approve <user_id>` - Approve Request
- Approves a user's access request
- Adds user to allowed list
- Notifies the user

**Usage:**
```
/approve 123456789
```

#### `/reject <user_id>` - Reject Request
- Rejects a user's access request
- Removes request from pending list
- Notifies the user

**Usage:**
```
/reject 123456789
```

## How It Works

### 1. User Requests Access

When a user sends `/request`:
- Request is stored in `allowed_users.json` (pending_requests)
- All admins are notified with a message
- Inline buttons for quick approve/reject are included
- User gets confirmation message

### 2. Admin Reviews Request

Admins can:
- See notification when request comes in (with buttons)
- Use `/requests` to see all pending requests
- Approve/reject via buttons or commands

### 3. Admin Approves/Rejects

When admin approves:
- User is added to allowed list
- Request is removed from pending
- User is notified automatically

When admin rejects:
- Request is removed from pending
- User is notified automatically

## Data Storage

Requests are stored in `allowed_users.json`:

```json
{
  "allowed_users": [123456789],
  "admin_users": [987654321],
  "pending_requests": {
    "555123456": {
      "username": "John Doe",
      "timestamp": 1704240000.0,
      "message_id": 12345
    }
  }
}
```

## Features

### ✅ **Automatic Notifications**
- Admins get notified when someone requests access
- Users get notified when approved/rejected

### ✅ **Quick Actions**
- Inline buttons for instant approve/reject
- No need to type user IDs

### ✅ **Request Management**
- View all pending requests at once
- See request timestamps
- Easy to approve/reject multiple users

### ✅ **User-Friendly**
- Clear messages for users
- Status updates (pending, approved, rejected)
- No need to contact admin manually

## Example Scenarios

### Scenario 1: New User Requests Access

```
1. User: /start
   Bot: 🚫 Access Denied. Use /request to request access.

2. User: /request
   Bot: ✅ Access Request Submitted! You will be notified when reviewed.

3. Admin receives notification:
   🔔 New Access Request
   👤 User: John Doe
   🆔 ID: 123456789
   [✅ Approve] [❌ Reject]

4. Admin clicks: ✅ Approve
   Bot: ✅ Approved! User has been notified.

5. User receives:
   ✅ Access Approved! You can now use the bot!
```

### Scenario 2: Admin Reviews Multiple Requests

```
1. Admin: /requests
   Bot: ⏳ Pending Access Requests (3):
        👤 John Doe
        🆔 ID: 123456789
        [✅ Approve] [❌ Reject]
        
        👤 Jane Smith
        🆔 ID: 987654321
        [✅ Approve] [❌ Reject]
        
        ...

2. Admin clicks approve buttons for each
3. Users are notified automatically
```

### Scenario 3: Admin Rejects Request

```
1. Admin: /reject 123456789
   Bot: ❌ Request Rejected
        👤 User: John Doe
        🆔 ID: 123456789
        User has been notified.

2. User receives:
   ❌ Access Request Rejected
   Your access request has been rejected.
   If you believe this is a mistake, please contact the bot administrator.
```

## Integration with Existing Features

### Works With:
- ✅ Dynamic user management
- ✅ Admin system
- ✅ User verification
- ✅ `/adduser` command (admins can still add users directly)

### Request vs Direct Add:

**Request Flow:**
- User requests → Admin approves → User added

**Direct Add:**
- Admin uses `/adduser` → User added immediately

Both methods work and are stored the same way!

## Troubleshooting

### "I sent /request but nothing happened"

**Check:**
- Is `ENABLE_USER_VERIFICATION=true`?
- Is `USE_DYNAMIC_USER_MANAGEMENT=true`?
- Are there any admins? (If no admins, use `/adduser` first)

### "Admin didn't get notification"

**Check:**
- Is admin in the admin list? (Use `/listusers` to check)
- Check bot logs for errors
- Admin might have blocked the bot

### "Request disappeared"

**Possible reasons:**
- Request was approved/rejected
- Request expired (if you implement expiration)
- File was manually edited

### "Can't approve/reject from buttons"

**Check:**
- Are you an admin? (Use `/listusers` to verify)
- Is the request still pending? (Use `/requests` to check)
- Check bot logs for errors

## Summary

**Complete Access Request Flow:**
1. ✅ Users can request access (`/request`)
2. ✅ Admins get notified automatically
3. ✅ Admins can approve/reject via buttons or commands
4. ✅ Users are notified of decisions
5. ✅ Requests are stored persistently
6. ✅ Easy to manage multiple requests

**This makes the bot much more user-friendly!** Users don't need to contact admins manually - everything happens through the bot.
