#!/bin/sh
num_envs=$1

tmux new-session \; \
send-keys "workon rosnav" C-m \; \
send-keys "roslaunch arena_bringup start_training_all_in_one_planner.launch num_envs:=$num_envs" C-m\; \
split-window -h \; \
send-keys 'workon rosnav' C-m \; \
send-keys 'source catkin_ws/devel/setup.zsh' C-m \; \
send-keys 'roscd arena_local_planner_drl/' C-m \; \
send-keys "python3 scripts/training/train_all_in_one_agent.py --agent AGENT_2 --eval_log --tb --n_envs $num_envs --agent_name 2xteb_drl4_rule07_policy2 --all_in_one_config 2xteb_drl4.json" C-m \; \
split-window -h \; \
send-keys 'roslaunch arena_bringup visualization_training.launch use_rviz:=true rviz_file:=allinone_train' \; \
select-layout even-horizontal \; \
split-window -v \; \
select-pane -t 2 \; \
