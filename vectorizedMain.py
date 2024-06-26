import numpy as np
import torch
from TD3 import TD3
import os
import time
import utils
from utils import SEED
import csv

import gymnasium as gym
import env

import argparse

MAX_TIME_STEPS = 1000000
max_episode_steps = 2000

NUM_PARALLEL_ENVS = 3

#Options to change expl noise and tau

LOWER_EXPL_NOISE = {"On" : True, "Reward_Threshold":14000, 'Value': 0.005}
LOWER_TAU = {"On" : True, "Reward_Threshold":18000, 'Timesteps_Threshold' : 10000, 'Value': 0.001}


#load already trained policy
LOAD_POLICY = {"On": False, 'init_time_steps': 1e4}

#Avg reward termination condition

TERMIN_THRESHOLD = {"reward": 63, "timesteps": 45000}

# Time steps below which a standard training iteration param is passed
MIN_EPS_TIMESTEPS = 500


# Runs policy for X episodes and returns average reward
def evaluate_policy(policy, eval_episodes=5):
	avg_reward = 0
	num_fin_episodes = 0
	obs, info = envs.reset()
	avg = 0
	while num_fin_episodes < eval_episodes:
		action = policy.select_vectorized_action(np.array(obs))
		obs, reward, done, _, info = envs.step(action)
		avg_reward += reward
			
        # when an episode ends in any environment
		if '_final_observation' in info.keys():
			
			finished = info['_final_observation']
			num_fin = np.count_nonzero(finished)
			
			num_fin_episodes += num_fin
			
			avg += np.sum(avg_reward[finished])
			
	avg /= num_fin_episodes
	print("---------------------------------------")
	print("Evaluation over %d episodes: %f" % (num_fin_episodes, avg))
	print("---------------------------------------")
	return avg

if __name__ == "__main__":

	parser = argparse.ArgumentParser(description='Settings for env')

	parser.add_argument("--penalize_oscl", default=True)
	parser.add_argument("--timestp_thr", default=None)
	parser.add_argument("--var_speed", default=False)		
	parser.add_argument("--accel_brake", default=False)
	parser.add_argument("--render_mode", default="human")
	parser.add_argument("--load_policy", default=None)
	parser.add_argument("--load_model", default=None)
	args = parser.parse_args()


	if args.timestp_thr is not None:
		TERMIN_THRESHOLD["timesteps"] = int(args.timestp_thr)
	elif args.var_speed:
		TERMIN_THRESHOLD["reward"] = 80
	elif args.accel_brake:
		TERMIN_THRESHOLD["reward"] = 100

                
	start_timesteps = 1e3           	# How many time steps purely random policy is run for
	eval_freq = 1e4			            # How often (time steps) we evaluate
	max_timesteps = MAX_TIME_STEPS 		# Max time steps to run environment for
	save_models = True			    	# Whether or not models are saved

	expl_noise=0.02	                	# Std of Gaussian exploration noise
	batch_size=256		                # Batch size for both actor and critic
	tau=0.002	                    	# Target network update rate
	policy_noise=0.1		            # Noise added to target policy during critic update
	noise_clip=0.25	                  	# Range to clip target policy noise



	print("---------------------------------------")
	print ("                 TD3 ")
	print("---------------------------------------")

	if not os.path.exists("./results"):
		os.makedirs("./results")
	if save_models and not os.path.exists(utils.model_dir):
		os.makedirs(utils.model_dir)

	# Specify the filenames/driectories for respective tasks (const speed, var speed, accl)
	if args.accel_brake:
		LOGS_FILEPATH = utils.logs_filepath_accl
		file_name = utils.file_name_accl
		policies_dir = utils.policies_dir_accl

		if not os.path.exists(utils.policies_dir_accl):
			os.makedirs(utils.policies_dir_accl)

	elif args.var_speed:
		LOGS_FILEPATH = utils.logs_filepath_var_speed
		file_name = utils.file_name_var
		policies_dir = utils.policies_dir_var_speed

		if not os.path.exists(utils.policies_dir_var_speed):
			os.makedirs(utils.policies_dir_var_speed)

	else:
		LOGS_FILEPATH = utils.logs_filepath
		file_name = utils.file_name
		policies_dir = utils.policies_dir

		if not os.path.exists(utils.policies_dir):
			os.makedirs(utils.policies_dir)
		
	if not os.path.exists('./benchmarks/logs/'):
			os.makedirs('./benchmarks/logs/')
	
	with open(LOGS_FILEPATH, 'w', newline='') as file:
		log_writer = csv.writer(file)

		# Write headings
		log_writer.writerow(['r', 'l'])
	


	
	# Register environment
	env_id  = 'center_maintaining'
	env.registerEnv(env_id)
	
	# Initialise vectorized environments
	num_envs= NUM_PARALLEL_ENVS
	envs = gym.make_vec(
		env_id, 									# env id for custom registered env
		num_envs=num_envs, 							# num parallel env for vectorization 
		render_mode=args.render_mode,				# render pygame display option
		var_speed=args.var_speed,					# train for variable speeds
		accel_brake = args.accel_brake,				# train for acceleration and brake
		penalize_oscl = int(args.penalize_oscl),	# penalize oscilations
		max_episode_timesteps= max_episode_steps    # maximum timesteps for an episode
		)
	
	#Counter to track finished episode within one iteration of parallel runs
	num_fin_episodes = 0

	# Set seeds
	torch.manual_seed(SEED)
	np.random.seed(SEED)
	
	# State dimension for individual(single) environments
	state_dim = envs.single_observation_space.shape[0]
	action_dim = envs.single_action_space.shape[0] 
	max_action = float(envs.single_action_space.high[0])

	# Initialize policy
	policy = TD3(state_dim, action_dim, max_action, policy_noise=policy_noise, noise_clip=noise_clip)

	# Load already trained policy

	#Load policy or model based on input
	if args.load_policy is not None:
		filename = "Policy_" + str(args.load_policy)
		directory = "./policies"
		policy.load(filename, directory)
		start_timesteps = 0
	elif args.load_model is not None:
		filename = "TD3_" + args.load_model
		directory = "./pytorch_models"
		policy.load(filename, directory)
		start_timesteps = 0
	
	# Init replay buffer
	replay_buffer = utils.ReplayBuffer()
	
	# Evaluate untrained policy
	evaluations = []#evaluations = [evaluate_policy(policy)] 

	# Init counters
	total_timesteps = 0
	timesteps_since_eval = 0
	train_iteration = 0
	eval_count = 0
	
	# array to track if the frist episode in each parallel env have ended 
	all_done = np.full(num_envs, True, dtype=bool)
	
	# For each train iteration
	episode_count = 0
	avg_reward = 0
	avg_CTE = 0

	t0 = time.time()

	while total_timesteps < max_timesteps:
		
		# all_done: When the first three episodes in each environment have finished 
		if all_done.all(): 
			
			# calculate average reward over episodes
			if num_fin_episodes!=0: 
				avg_reward /= num_fin_episodes
				avg_reward_per_tile /= num_fin_episodes
				avg_CTE /= episode_timesteps / env.ROAD_HALF_WIDTH
				avg_r_ts = avg_reward / episode_timesteps

			### Training after all_done as defined ###
			###########################################
			if total_timesteps != 0 and (not LOAD_POLICY['On'] or total_timesteps>=LOAD_POLICY["init_time_steps"]):
				
				print("\nData Stats:\nTotal T: %d   Train itr: %d   Episodes T: %d Best Reward: %.2f  Avg Reward: %.2f  Avg Reward/Tile: %.2f  Avg CTE: %.2f AVG R/TS: %.2f  \n--  Wallclk T: %d sec" % \
					(total_timesteps, train_iteration, episode_timesteps, max_reward, avg_reward, avg_reward_per_tile, avg_CTE, avg_r_ts, int(time.time() - t0)))
				
				# End learning condtion
				if avg_reward_per_tile >= TERMIN_THRESHOLD['reward'] and total_timesteps>=TERMIN_THRESHOLD["timesteps"]:
					print("\n\nAvg Reward/Tile Threshold Met -- Training Terminated\n")

					break
					
				# Lower Tau
				if LOWER_TAU["On"] and avg_reward >= LOWER_TAU["Reward_Threshold"] and total_timesteps>=LOWER_TAU["Timesteps_Threshold"]:
					tau = LOWER_TAU["Value"]
					print("\n-------Lowered Tau to %f \n" % LOWER_TAU["Value"])
					LOWER_TAU["On"] = False

                # Lower exploration noise 
				if LOWER_EXPL_NOISE["On"] and avg_reward >= LOWER_EXPL_NOISE["Reward_Threshold"]:
					expl_noise = LOWER_EXPL_NOISE["Value"]
					print("\n-------Lowered expl noise to %f \n" % LOWER_EXPL_NOISE["Value"])
					LOWER_EXPL_NOISE["On"] = False

				# save each policy with above stats before training
				policy.save("Policy_%d" % (train_iteration), directory=policies_dir)

				print("\nTraining: ", end=" ")

				# Conditional to pass standardized training iterations to train function
				if episode_timesteps < MIN_EPS_TIMESTEPS:
					print("STANDARDIZED TRAINING ITERATIONS")
					policy.train(MIN_EPS_TIMESTEPS, replay_buffer, tau, batch_size)
				else:
					policy.train(episode_timesteps, replay_buffer, tau, batch_size)
				
				train_iteration += 1 
				
				print("-Finished ")
				print("\n-----------------------")
			
			# Evaluate episode
			if timesteps_since_eval >= eval_freq:
				timesteps_since_eval %= eval_freq
				eval_score = evaluate_policy(policy)
				evaluations.append(eval_score)

				# Saving evaluated policy as TD3_0
				if save_models: policy.save(file_name + str(eval_count), directory=utils.model_dir)
				np.save("./results/%s" % (file_name), evaluations) 

				eval_count+=1
			

			### Reseting environment and var for new data collection iteration ###
   			######################################################################
			print("\nCollecting data:")
			
			# Reseting environment
			obs, info = envs.reset(seed=[SEED + i for i in range(num_envs)])
			SEED+=num_envs
			
			# Reseting flags/var
			all_done = np.full(num_envs, False, dtype=bool)
			finished = np.full(num_envs, False, dtype=bool)
			episode_reward = np.zeros(num_envs, dtype=float)
			
			# Reseting counters
			episode_timesteps = 0
			max_reward = None
			avg_reward = 0
			avg_reward_per_tile = 0
			num_fin_episodes = 0

		# Select action randomly or according to policy
		if total_timesteps == start_timesteps:
			print("\n\n\nPolicy actions started\n\n\n")

		if total_timesteps < start_timesteps:
			# Random actions for each environment
			action = envs.action_space.sample()
		else:
			# Note: for vectorized env a new select_action function was implemented in TD3
			action = policy.select_vectorized_action(obs)
			
			# Adding exploraiton noise to action(vector)
			if expl_noise != 0: 
				action = (action + np.random.normal(0, expl_noise, size=envs.single_action_space.shape[0])).clip(envs.single_action_space.low, envs.single_action_space.high)

		# Perform action: step function returns vectors
		new_obs, reward, done, truncated, info = envs.step(action)

		episode_reward += reward

		#updating avg CTE 
		avg_CTE+= sum([abs(cte[1]) for cte in new_obs])

        
		# Episode ends in a environment(s)
		if '_final_observation' in info.keys():
			
			# bool vector marking envs with finished episodes
			finished = info['_final_observation']

			# current number of finished environments
			num_fin = np.count_nonzero(finished)
			
			# total number of finsihed envs
			num_fin_episodes += num_fin

			# number of finished episodes in current data collection iteration
			episode_count += num_fin
			
            # all_done marks the environments whose episodes ended
			all_done = np.logical_or(all_done, finished)
			
			print("Episode %d reward for finished enviroments:" % episode_count, episode_reward[finished])

            # Set best reward / max reward among finished episodes
			if max_reward is not None:
				max_reward = max(max_reward, max(episode_reward[finished]))
			else:
				max_reward = max(episode_reward[finished])

			# cumulative sum for eventual avg calculation at the end of data collection
			avg_reward += sum(episode_reward[finished])
			
			#set episode reward for respective environments in the episode_reward vector to 0
			episode_reward[finished] = 0

			#Avg reward per tile
			for i in range(num_fin):
				avg_reward_per_tile += info['final_info'][finished][i]["rewardPerTile"]


		# Store data in replay buffer flattening the obtained vectors into the replay buffer
		for i in range(num_envs):
			if '_final_observation' in info.keys() and info['_final_observation'][i] == True:
				replay_buffer.add(obs[i], info['final_observation'][i], action[i], reward[i], 1)
			else:
				replay_buffer.add(obs[i], new_obs[i], action[i], reward[i], 0)

		# Store new obs as obs before action is taken
		obs = new_obs

        # Episode time_steps counted with consideration of all paralel environments
		episode_timesteps += num_envs
		total_timesteps += num_envs
		timesteps_since_eval += num_envs

	# Final evaluation after termination of learning
	evaluations.append(evaluate_policy(policy))
  
	if save_models: policy.save("%s" % (file_name + "Final"), directory=utils.model_dir)
	np.save("./results/%s" % (file_name + "Final"), evaluations) 
	print("Final model saved as: " + file_name + "Final") 
	envs.close()

	envs.close()