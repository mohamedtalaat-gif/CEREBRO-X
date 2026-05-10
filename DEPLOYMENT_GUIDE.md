# CEREBRO-X Manual Deployment Guide
## Step-by-Step Instructions for GitHub Pages

**Estimated Time:** 10-15 minutes  
**Prerequisites:** GitHub account, files downloaded from this package

---

## Method 1: Web Interface (Easiest - No Command Line)

### Step 1: Prepare Files on Your Computer

1. Download all 5 deliverable files from this package
2. Create a folder structure like this:

```
CEREBRO-X/
├── index.html                    (rename cerebro-x-github-page.html)
├── demo/
│   └── standalone.html           (rename cerebro-x-demo-standalone.html)
├── docs/
│   ├── CEREBRO-X_White_Paper_v2.0.pdf
│   └── QUICK_START_PROFESSIONAL.md
├── README.md
├── Primary_Logo.png              (from your existing repository)
└── Engine - Background system, pattern, visual language.png
```

### Step 2: Upload to GitHub

**Option A: Drag & Drop (Simple)**

1. Go to: `https://github.com/mohamedtalaat-gif/CEREBRO-X`
2. Click "Add file" → "Upload files"
3. Drag all files from your local folder
4. Scroll down, add commit message: "Deploy production website"
5. Click "Commit changes"

**Option B: GitHub Desktop (Recommended for multiple files)**

1. Download GitHub Desktop: https://desktop.github.com/
2. Clone your repository: File → Clone Repository → `mohamedtalaat-gif/CEREBRO-X`
3. Copy all files into the cloned folder
4. GitHub Desktop will show all changes
5. Add commit message: "Deploy production website"
6. Click "Commit to main"
7. Click "Push origin"

### Step 3: Enable GitHub Pages

1. Go to: `https://github.com/mohamedtalaat-gif/CEREBRO-X/settings/pages`
2. Under "Build and deployment":
   - **Source:** Deploy from a branch
   - **Branch:** main
   - **Folder:** / (root)
3. Click "Save"
4. Wait 1-2 minutes for deployment
5. Your site will be live at: `https://mohamedtalaat-gif.github.io/CEREBRO-X/`

### Step 4: Verify Deployment

**Test these URLs:**
- Main page: `https://mohamedtalaat-gif.github.io/CEREBRO-X/`
- Demo: `https://mohamedtalaat-gif.github.io/CEREBRO-X/demo/standalone.html`
- White Paper: `https://mohamedtalaat-gif.github.io/CEREBRO-X/docs/CEREBRO-X_White_Paper_v2.0.pdf`

**Check these elements:**
- [ ] Primary logo loads at top of page
- [ ] Engine pattern icon shows in navigation
- [ ] Meteors are falling in background
- [ ] All buttons have consistent size
- [ ] White Paper section displays correctly

---

## Method 2: Command Line (Git)

### Prerequisites

- Git installed: `git --version`
- GitHub account connected: `git config --global user.name "Your Name"`

### Step 1: Clone Repository

```bash
# Clone your repository
git clone https://github.com/mohamedtalaat-gif/CEREBRO-X.git
cd CEREBRO-X
```

### Step 2: Add Files

```bash
# Copy files into repository (adjust paths as needed)
cp ~/Downloads/cerebro-x-github-page.html ./index.html
cp ~/Downloads/cerebro-x-demo-standalone.html ./demo/standalone.html
cp ~/Downloads/CEREBRO-X_White_Paper_v2.0.pdf ./docs/
cp ~/Downloads/README.md ./
cp ~/Downloads/QUICK_START_PROFESSIONAL.md ./docs/

# Create directories if needed
mkdir -p demo docs
```

### Step 3: Commit and Push

```bash
# Stage all files
git add .

# Commit with message
git commit -m "Deploy CEREBRO-X production website"

# Push to GitHub
git push origin main
```

### Step 4: Enable GitHub Pages

Follow Step 3 from Method 1 above.

---

## Method 3: Automated Script (Fastest)

Use the provided `deploy-to-github.sh` script:

```bash
# Make script executable
chmod +x deploy-to-github.sh

# Run deployment
./deploy-to-github.sh
```

The script will:
1. Copy all files to correct locations
2. Stage files for commit
3. Create commit with timestamp
4. Push to GitHub
5. Display next steps for enabling Pages

---

## Troubleshooting

### Issue: Images Not Loading

**Problem:** Primary logo or Engine pattern doesn't appear

**Solution:**
1. Verify files exist in repository root:
   - `Primary_Logo.png`
   - `Engine - Background system, pattern, visual language.png`
2. Check file names match exactly (case-sensitive)
3. Update image URLs in `index.html` if needed:

```html
<!-- Line ~88 -->
<img src="https://raw.githubusercontent.com/mohamedtalaat-gif/CEREBRO-X/main/Primary_Logo.png">

<!-- Line ~237 -->
<img src="https://raw.githubusercontent.com/mohamedtalaat-gif/CEREBRO-X/main/Engine%20-%20Background%20system%2C%20pattern%2C%20visual%20language.png">
```

### Issue: GitHub Pages Not Deploying

**Problem:** Site not available after enabling Pages

**Solutions:**
1. Wait 2-3 minutes (GitHub Pages takes time to build)
2. Check Settings → Pages for deployment status
3. Ensure `index.html` exists in repository root
4. Check for build errors in Actions tab

### Issue: 404 Error on Demo Page

**Problem:** `/demo/standalone.html` returns 404

**Solution:**
1. Verify `demo/` folder exists in repository
2. Verify `standalone.html` is inside `demo/` folder
3. Check URL spelling: `/demo/standalone.html` (lowercase)

### Issue: Git Push Requires Authentication

**Problem:** "Authentication failed" when pushing

**Solutions:**

**Option 1: Personal Access Token (Recommended)**
1. Go to: https://github.com/settings/tokens
2. Generate new token (classic)
3. Select scopes: `repo` (all checkboxes)
4. Copy token
5. When prompted for password, paste token instead

**Option 2: SSH Key**
1. Follow: https://docs.github.com/en/authentication/connecting-to-github-with-ssh
2. Clone using SSH URL: `git@github.com:mohamedtalaat-gif/CEREBRO-X.git`

---

## Post-Deployment Checklist

After successful deployment:

### Immediate Testing
- [ ] Visit main page and verify all sections load
- [ ] Test mobile responsiveness (resize browser)
- [ ] Click all navigation links
- [ ] Verify White Paper PDF downloads
- [ ] Check demo page functionality

### Share Links
- [ ] Update LinkedIn profile with GitHub Pages URL
- [ ] Add link to CV/resume
- [ ] Include in email signature
- [ ] Share with Prof. Tang and Prof. Kros

### Optional Enhancements
- [ ] Add Google Analytics (create `ANALYTICS.md` for instructions)
- [ ] Add custom domain (yourdomain.com)
- [ ] Create additional demo pages for other drugs
- [ ] Record screen capture video walkthrough

---

## Quick Reference: Important URLs

**Repository:** `https://github.com/mohamedtalaat-gif/CEREBRO-X`  
**Live Site:** `https://mohamedtalaat-gif.github.io/CEREBRO-X/`  
**Settings:** `https://github.com/mohamedtalaat-gif/CEREBRO-X/settings/pages`  
**Deployments:** `https://github.com/mohamedtalaat-gif/CEREBRO-X/deployments`

---

## Need Help?

If you encounter issues not covered here:

1. Check GitHub Pages status: https://www.githubstatus.com/
2. Review GitHub Pages documentation: https://docs.github.com/en/pages
3. Verify file names match exactly (case-sensitive)
4. Clear browser cache and test in incognito mode

---

**Deployment Guide Version:** 1.0  
**Last Updated:** May 10, 2026  
**Prepared For:** Muhammad Talaat | CEREBRO-X Project
