#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status
set -e

# Setup color outputs
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0;0m' # No Color

echo -e "${BLUE}=== eUczelnia Bridge Installation Script ===${NC}"

# 1. Verify Python Version (3.11+)
echo "Checking Python version..."
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo -e "${RED}Error: Python is not installed. Please install Python 3.11 or newer.${NC}" >&2
    exit 1
fi

PYTHON_VERSION=$($PYTHON_CMD -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [ "$MAJOR" -lt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 11 ]; }; then
    echo -e "${RED}Error: Python version must be 3.11 or newer. Found: $PYTHON_VERSION${NC}" >&2
    exit 1
fi
echo -e "${GREEN}Python $PYTHON_VERSION detected.${NC}"

# 2. Create Virtual Environment
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d "venv" ]; then
    echo "Creating virtual environment in venv/..."
    $PYTHON_CMD -m venv venv
    echo -e "${GREEN}Virtual environment created.${NC}"
else
    echo "Virtual environment already exists."
fi

# 3. Upgrade Pip & Install Dependencies
echo "Installing dependencies from requirements.txt..."
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
echo -e "${GREEN}Dependencies installed successfully.${NC}"

# 4. Install Playwright browser
echo "Installing Playwright Chromium browser binaries..."
./venv/bin/playwright install chromium
echo -e "${GREEN}Playwright browser binaries installed.${NC}"

# 5. Initialize config files if not already present
echo "Initializing configuration files..."
if [ ! -f "config/config.json" ]; then
    cp config/config.json.template config/config.json
    echo -e "${GREEN}Created config/config.json from template.${NC}"
else
    echo "config/config.json already exists, skipping."
fi

if [ ! -f "config/.env" ]; then
    cp config/.env.template config/.env
    echo -e "${GREEN}Created config/.env from template.${NC}"
    echo -e "${BLUE}Please update config/.env with your eUczelnia login details.${NC}"
else
    echo "config/.env already exists, skipping."
fi

# 6. Ensure data directory has .gitkeep
mkdir -p data
touch data/.gitkeep

echo -e "\n${GREEN}=== Installation Complete! ===${NC}"
echo -e "Next steps:"
echo -e "  1. Edit ${BLUE}config/.env${NC} and put your CAS credentials."
echo -e "  2. Edit ${BLUE}config/config.json${NC} if you need to configure your AI gateway."
echo -e "  3. Log in to Moodle: ${BLUE}./venv/bin/python login/login.py --output data/session.json${NC}"
echo -e "  4. Start daemon: ${BLUE}./venv/bin/python daemon/daemon.py --conversation-id <CONV_ID> --user-id <USER_ID> --sesskey <SESSKEY> --cookie-name <COOKIE_NAME> --cookie-value <COOKIE_VALUE>${NC}"
echo -e "For detailed guides, check ${BLUE}SKILL.md${NC} or ${BLUE}README.md${NC}."
