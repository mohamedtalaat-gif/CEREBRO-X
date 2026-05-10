#!/bin/bash
# CEREBRO-X GitHub Pages Deployment Script
# Automates the complete deployment process
# Usage: ./deploy-to-github.sh

set -e  # Exit on any error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}  CEREBRO-X GitHub Pages Deployment Script${NC}"
echo -e "${GREEN}================================================${NC}\n"

# Configuration
REPO_NAME="CEREBRO-X"
GITHUB_USERNAME="mohamedtalaat-gif"
BRANCH="main"

# Check if git is installed
if ! command -v git &> /dev/null; then
    echo -e "${RED}Error: git is not installed${NC}"
    echo "Please install git first: https://git-scm.com/downloads"
    exit 1
fi

# Check if we're in a git repository
if [ ! -d ".git" ]; then
    echo -e "${YELLOW}Not a git repository. Initializing...${NC}"
    git init
    git remote add origin "https://github.com/${GITHUB_USERNAME}/${REPO_NAME}.git"
fi

# Step 1: Copy files to repository root
echo -e "${YELLOW}Step 1: Copying deliverables to repository...${NC}"

# Create docs directory for White Paper
mkdir -p docs
mkdir -p demo
mkdir -p assets

# Copy files
cp cerebro-x-github-page.html index.html
cp cerebro-x-demo-standalone.html demo/standalone.html
cp CEREBRO-X_White_Paper_v2.0.pdf docs/
cp README.md .
cp QUICK_START_PROFESSIONAL.md docs/

echo -e "${GREEN}✓ Files copied successfully${NC}\n"

# Step 2: Stage files
echo -e "${YELLOW}Step 2: Staging files for commit...${NC}"
git add index.html
git add demo/standalone.html
git add docs/CEREBRO-X_White_Paper_v2.0.pdf
git add README.md
git add docs/QUICK_START_PROFESSIONAL.md

# Check if Primary_Logo.png exists
if [ -f "Primary_Logo.png" ]; then
    git add Primary_Logo.png
    echo -e "${GREEN}✓ Primary_Logo.png found and staged${NC}"
else
    echo -e "${YELLOW}⚠ Primary_Logo.png not found - please ensure it's in the repository${NC}"
fi

# Check if Engine pattern exists
if [ -f "Engine - Background system, pattern, visual language.png" ]; then
    git add "Engine - Background system, pattern, visual language.png"
    echo -e "${GREEN}✓ Engine pattern image found and staged${NC}"
else
    echo -e "${YELLOW}⚠ Engine pattern image not found - please ensure it's in the repository${NC}"
fi

echo -e "${GREEN}✓ All files staged${NC}\n"

# Step 3: Commit
echo -e "${YELLOW}Step 3: Creating commit...${NC}"
COMMIT_MESSAGE="Deploy CEREBRO-X production website - $(date +%Y-%m-%d)"
git commit -m "$COMMIT_MESSAGE"
echo -e "${GREEN}✓ Commit created: $COMMIT_MESSAGE${NC}\n"

# Step 4: Push
echo -e "${YELLOW}Step 4: Pushing to GitHub...${NC}"
echo -e "${YELLOW}You may be prompted for GitHub credentials${NC}\n"

git push -u origin $BRANCH

echo -e "${GREEN}✓ Push completed successfully${NC}\n"

# Step 5: Instructions for GitHub Pages
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}  Deployment Complete!${NC}"
echo -e "${GREEN}================================================${NC}\n"

echo -e "${YELLOW}Next Steps:${NC}"
echo -e "1. Go to: https://github.com/${GITHUB_USERNAME}/${REPO_NAME}/settings/pages"
echo -e "2. Under 'Source', select 'Deploy from a branch'"
echo -e "3. Choose branch: '${BRANCH}', folder: '/ (root)'"
echo -e "4. Click 'Save'"
echo -e "\n${GREEN}Your site will be available at:${NC}"
echo -e "${GREEN}https://${GITHUB_USERNAME}.github.io/${REPO_NAME}/${NC}\n"

echo -e "${YELLOW}File Structure:${NC}"
echo -e "├── index.html              (Main GitHub Page)"
echo -e "├── demo/"
echo -e "│   └── standalone.html     (Standalone Demo)"
echo -e "├── docs/"
echo -e "│   ├── CEREBRO-X_White_Paper_v2.0.pdf"
echo -e "│   └── QUICK_START_PROFESSIONAL.md"
echo -e "├── assets/                 (Your images)"
echo -e "│   ├── Primary_Logo.png"
echo -e "│   └── Engine - Background system, pattern, visual language.png"
echo -e "└── README.md\n"

echo -e "${GREEN}Deployment script completed successfully!${NC}"
