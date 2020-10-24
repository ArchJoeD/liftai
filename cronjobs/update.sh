#!/bin/bash

path="/home/pi/";
fatal_error_log_file="$path/liftai_logs/script_fatal_errors.log"
git_path="python-development/";

cd $path$git_path;
echo $path$git_path;

result=`git pull 2>&1`

if echo "$result" | grep "fatal: loose object"; then
  echo "A fatal error occurred, deleting the respository and re-cloning it..."
  echo "`date`  Fatal error in git repository, deleting and re-cloning: $result" >> $fatal_error_log_file
  cd $path
  rm -fr $path$git_path
  git clone git@github.com:LiftAI/python-development.git
  cd $path$git_path
  result="Force a software upgrade in case there was a change"
fi


#  Do nothing if either already up to date or a connectivity problem.
if echo "$result" | grep -e 'up-to-date' -e 'Could not read'; then
    echo "No changes"
else
    echo "Changes"
    ./deploy_clean_raspbian.sh
fi

echo -e '\n Complete';