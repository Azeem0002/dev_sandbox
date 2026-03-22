#### VScode
- code .
- keybinding: "run python file"= ctrl + r
- 

#### Git: create a new repository on the command line

echo "# repo" >> README.md
- init
- branch -M main (“Work on a different version without touching the main one”)
# Analogy:
# git add = selecting pages
# git commit = submitting them and stamping date + message
# Main branch = original story. v1
# New branch = alternate storyline. v2
- add . or README.md  (Moves changes from working area → staging area) i.e “I want these changes included in the next save”
- commit -m "initial commit"  (Saves staged changes permanently in Git history) i.e “Lock this version as a checkpoint”
- git remote add origin https://github.com/Azeem0002/calc.git
- push -u origin main

<!-- …or push an existing repository from the command line -->
- remote add origin https://github.com/Azeem0002/calc.-
- branch -M main
- push -u origin main

<!-- Configure multiple remotes and push once. -->
# 1. Verify you’re inside a git repo
git status





# Clean up old / broken remotes
Check existing remotes:
git remote -v

git remote remove both
git remote remove gitlab
git remote remove origin

# 2. Add single remotes
<!-- Add GitHub: -->
- git remote add github git@github.com:USERNAME/REPO.git (ssh version)
- git remote add origin https://github.com/Azeem0002/dev_sandbox.git (https version)

<!-- Verify: -->
git remote -v


# Mirror push remote (both) — GitHub + GitLab
git remote add both https://github.com/Azeem0002/dev_sandbox.git
git remote set-url --add both https://gitlab.com/Azeem0002/dev_sandbox.git

<!-- Verify: -->
git remote -v
<!-- Expected Output: -->

both    https://github.com/Azeem0002/dev_sandbox.git (fetch)
both    https://github.com/Azeem0002/dev_sandbox.git (push)
both    https://gitlab.com/Azeem0002/dev_sandbox.git (push)

<!-- Set upstream for convenience -->
git branch --set-upstream-to=origin/main main
- Now git pull automatically pulls from GitHub (origin)
- You avoid accidentally pulling from GitLab


| Action         | Command                                 |
| -------------- | --------------------------------------- |
| Pull updates   | `git pull` (pulls from `origin`)        |
| Stage & commit | `git add .` → `git commit -m "message"` |
| Push to both   | `git push both main`                    |

# or push:
git push -u origin main      # first push
git push REMOTE_NAME(both, origin) main

# pull from origin (github)
git pull origin main
<!-- or -->
# Pull from a specific remote:
git pull gitlab main

# remove 
git remote remove REMOTE_NAME(e.g both, origin)
<!-- or -->
# delete single url
git remote set-url --delete REMOTE_NAME git@gitlab.comAzeem0002/dev_sandbox.git

# Optional alias (push to both with one command)
<!-- Edit your global git config: -->
git config --global alias.pushboth "push both main"

<!-- Now you can just do: -->
git pushboth