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


echo "Deploying files from $SOURCE_DIR"
# Find files in the source directory and copy them
# Using null-terminated output/input for safety with special filenames
find "$SOURCE_DIR" -maxdepth 1 -type f -print0 | while IFS= read -r -d $'\0' file; do
    filename=$(basename "$file")

    if [ "$DEPLOY_MODE" == "source_only" ]; then
        if [ "$filename" == "n64.txt" ]; then
            continue
        fi
    fi

    remote_path="$DEST_DIR$filename"

    echo "Copying '$filename' to '$remote_path'..."
    $RSHELL_CMD cp "$file" "$remote_path"

    if [ $? -ne 0 ]; then
        echo "Error copying '$filename'. Deployment failed." >&2
        exit 1 # Exit on first error
    fi
done

# Check if the loop finished without errors (only relevant for 'all' mode)
if [ $? -ne 0 ] && [ "$DEPLOY_MODE" != "source_only" ]; then
     echo "Deployment loop failed." >&2
     exit 1
fi

echo "-----------------------------"
echo "Deployment completed successfully."
exit 0 