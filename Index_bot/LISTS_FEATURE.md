# Custom Lists Feature

## Overview

The bot now supports automatic channel detection and custom lists for filtering searches and library views across specific channels.

## Key Features

### 1. Automatic Channel Detection ✅

**No need to manually add channels!**

- When you add the bot as admin to a channel, it automatically detects and starts indexing
- Channels are registered automatically when files are uploaded
- Just add the bot as admin with "read messages" permission

### 2. Three Types of Views

#### A. Combined Index (All Channels)
- Default view showing all files from all channels
- Use: `/search <name>` or `/library <name>`
- Shows aggregate statistics across all channels

#### B. Channel-Specific Index
- View files from a single channel
- Use: `/channel_index @channel_name`
- Shows all files indexed from that specific channel

#### C. Multi-Channel Lists (Custom Lists)
- Create custom lists with selected channels
- Use: `/search <name> --list <list_name>` or `/library <name> --list <list_name>`
- Filter results to only show files from channels in your list

## Commands

### List Management

#### `/lists` - View All Lists
Shows all available lists including:
- **All Channels** (default, cannot be deleted)
- Your custom lists

#### `/create_list <name> <channels>` - Create Custom List
```
/create_list MyMovies @channel1 @channel2 @channel3
```

Creates a list with the specified channels. You can then use:
```
/search movie_name --list MyMovies
/library movie_name --list MyMovies
```

#### `/delete_list <name>` - Delete Custom List
```
/delete_list MyMovies
```

Deletes a custom list (cannot delete "All Channels" default list).

### Search & Browse

#### `/search <name> [--list <list>]` - Search with Optional Filter
```
/search Inception
/search Inception --list MyMovies
```

#### `/library <name> [--list <list>]` - Detailed View with Optional Filter
```
/library Inception
/library Inception --list MyMovies
```

#### `/channel_index <channel>` - View Single Channel Index
```
/channel_index @my_channel
```

Shows all files from that specific channel.

## Examples

### Example 1: Create a List for Movie Channels
```
/create_list Movies @movies_channel1 @movies_channel2
```

Then search only in those channels:
```
/search The Matrix --list Movies
```

### Example 2: Create a List for Series Channels
```
/create_list Series @series_channel1 @series_channel2
```

Then view library only from those channels:
```
/library Game of Thrones --list Series
```

### Example 3: View Single Channel
```
/channel_index @my_movies
```

Shows all movies indexed from @my_movies channel.

### Example 4: Combined View (All Channels)
```
/search The Matrix
```

Shows results from ALL channels combined.

## How It Works

1. **Automatic Detection:**
   - Bot receives message from channel it's admin of
   - Automatically registers channel in database
   - Starts indexing files immediately

2. **Custom Lists:**
   - Lists store channel IDs
   - When searching with `--list`, only files from those channels are shown
   - Lists persist across bot restarts

3. **Filtering:**
   - Search and library commands support `--list` parameter
   - If no list specified, shows results from all channels
   - Channel-specific view shows only that channel

## Use Cases

### Use Case 1: Separate Movie and Series Channels
```
/create_list Movies @movies1 @movies2
/create_list Series @series1 @series2

/search Inception --list Movies
/library Breaking Bad --list Series
```

### Use Case 2: Quality-Based Lists
```
/create_list HD @hd_channel1 @hd_channel2
/create_list SD @sd_channel1

/search movie_name --list HD
```

### Use Case 3: Source-Based Lists
```
/create_list Netflix @netflix_channel
/create_list Amazon @amazon_channel

/search movie_name --list Netflix
```

## Important Notes

- **Default "All Channels" list** cannot be deleted
- **Channels auto-detect** - no need to manually add them
- **Lists are user-created** - each user can create their own lists
- **Channel-specific view** shows all files, not just movies
- **Multi-channel lists** aggregate results from selected channels

## Migration from Old System

If you were using `/add_channel` before:
- You can still use it, but it's optional
- Channels are now auto-detected
- Old channels in database still work
- New channels are automatically added

## Tips

1. **Create lists for common searches:**
   - If you often search in specific channels, create a list
   - Makes searching faster and more focused

2. **Use descriptive list names:**
   - `Movies`, `Series`, `HD`, `SD`, etc.
   - Makes it easier to remember which list to use

3. **Combine with channel_index:**
   - Use `/channel_index` to see what's in a channel
   - Then create lists based on what you find
