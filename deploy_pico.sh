#!/bin/bash

# Script to copy files from the 'src' directory to the root filesystem
# of a connected Raspberry Pi Pico using rshell.
# Accepts an optional argument "source" to only copy n64.py.

# Configuration
SOURCE_DIR="src"
# Destination directory on the Pico (root)
DEST_DIR="/pyboard/"
# Full path to rshell if not in PATH
RSHELL_CMD="/Users/dudu/Library/Python/3.9/bin/rshell"

DEPLOY_MODE="all"
if [ "$1" == "source" ]; then
    DEPLOY_MODE="source_only"
fi

echo "--- Pico Deployment Script ---"

# Check if rshell exists at the specified path
if ! command -v $RSHELL_CMD &> /dev/null; then
    echo "Error: '$RSHELL_CMD' command not found." >&2
    echo "Please ensure rshell is installed and the path is correct." >&2
    if command -v rshell &> /dev/null; then
        echo "Hint: 'rshell' found in PATH, consider removing RSHELL_CMD override."
    else
        echo "Attempted install: pip3 install rshell"
    fi
    exit 1
fi

# Check if source directory exists
if [ ! -d "$SOURCE_DIR" ]; then
    echo "Error: Source directory '$SOURCE_DIR' not found." >&2
    exit 1
fi

echo "Using source directory: $SOURCE_DIR"
echo "Targeting destination: $DEST_DIR on Pico"
echo "Using rshell command: $RSHELL_CMD"

# --- Deployment Logic ---
if [ "$DEPLOY_MODE" == "source_only" ]; then
    # Deploy only n64.py
    SOURCE_FILE="$SOURCE_DIR/n64.py"
    TARGET_FILE="n64.py" # Filename on Pico
    REMOTE_PATH="$DEST_DIR$TARGET_FILE"
    echo "Deploying source only: $TARGET_FILE"

    if [ ! -f "$SOURCE_FILE" ]; then
        echo "Error: Source file '$SOURCE_FILE' not found." >&2
        exit 1
    fi

    echo "Copying '$TARGET_FILE' to '$REMOTE_PATH'..."
    $RSHELL_CMD cp "$SOURCE_FILE" "$REMOTE_PATH"

    if [ $? -ne 0 ]; then
        echo "Error copying '$TARGET_FILE'. Deployment failed." >&2
        exit 1
    fi

else
    # Deploy all files
    echo "Deploying all files from $SOURCE_DIR"
    # Find files in the source directory and copy them
    # Using null-terminated output/input for safety with special filenames
    find "$SOURCE_DIR" -maxdepth 1 -type f -print0 | while IFS= read -r -d $'\0' file; do
        filename=$(basename "$file")
        remote_path="$DEST_DIR$filename"

        echo "Copying '$filename' to '$remote_path'..."
        $RSHELL_CMD cp "$file" "$remote_path"

        if [ $? -ne 0 ]; then
            echo "Error copying '$filename'. Deployment failed." >&2
            exit 1 # Exit on first error
        fi
    done
fi

# Check if the loop finished without errors (only relevant for 'all' mode)
if [ $? -ne 0 ] && [ "$DEPLOY_MODE" != "source_only" ]; then
     echo "Deployment loop failed." >&2
     exit 1
fi

echo "-----------------------------"
echo "Deployment completed successfully."
exit 0 