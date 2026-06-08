#### VScode
- code .
- keybinding: "run python file"= ctrl + r
- 

#### Git: create a new repository on the command line

echo "# repo" >> README.md
- init
- branch -M main (“Work on a different version without touching the main one”)
* check current branch: git branch --show-current or git branch
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
<!-- https -->
git remote add origin https://github.com/Azeem0002/dev_sandbox.git
git remote set-url --add both https://gitlab.com/Azeem0002/dev_sandbox.git

<!-- ssh -->
git remote add origin/all git@gitlab.com:Azeem002/scraper_4.git
git remote set-url --add --push origin/all git@gitlab.com:Azeem002/scraper_4.git

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

<!-- Add branch -->
git branch new_branch_name
<!-- Delete branch -->
git branch -d branch_name


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

# Clean commits:
git reset --soft HEAD~5
git commit -m "clean commit"

# Optional alias (push to both with one command)
<!-- Edit your global git config: -->
git config --global alias.pushboth "push both main"

<!-- Now you can just do: -->
git pushboth


### Dualboot debian crash fix:

<!-- -Check current entries:  -->
- sudo efibootmgr -v
<!-- - Find your GRUB location:  -->
- sudo ls /boot/efi/EFI/
Look for debian/ or ubuntu/ or grub/ directory.
<!-- -Confirm the GRUB file exists: -->
sudo ls /boot/efi/EFI/debian/grubx64.efi
<!-- find your disk and partition: -->
- lsblk -f | grep -i efi
<!-- Add Debian to efibootmgr -->
- sudo efibootmgr -c -d /dev/sda -p 1 -L "debian" -l \\EFI\\debian\\grubx64.efi
<!-- Verify it was added -->
- sudo efibootmgr -v
<!-- Set as primary -->
- sudo efibootmgr -o X,other,entries
Replace X with Debian's boot number. e.g 0000,0001
<!-- Set fallback path (permanent protection) -->
- sudo mkdir -p /boot/efi/EFI/BOOT
sudo cp /boot/efi/EFI/debian/grubx64.efi /boot/efi/EFI/BOOT/BOOTX64.efi
<!-- update GRUB -->
- sudo update-grub

# bootable device not found
# 1. Mount your EFI partition
mount /dev/sda1 /boot/efi

# 2. Create fallback boot directory
mkdir -p /boot/efi/EFI/BOOT

# 3. Copy GRUB to fallback location
cp /boot/efi/EFI/debian/grubx64.efi /boot/efi/EFI/BOOT/BOOTX64.EFI

# 4. Copy GRUB config (important step)
cp -r /boot/grub /boot/efi/EFI/BOOT/

# 5. Reboot
reboot