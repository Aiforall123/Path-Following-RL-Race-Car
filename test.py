
import numpy as np
import TD3
from env import CarRacing
import argparse

#process file input
parser = argparse.ArgumentParser(description='Settings for env')
parser.add_argument("--policy_num", default=None)
parser.add_argument("--model_num", default="0")
args = parser.parse_args()

#Init env 
env = CarRacing(render_mode="human", var_speed=True)
state_dim = env.observation_space.shape[0]
action_dim = env.action_space.shape[0] 
max_action = float(env.action_space.high[0])

print(state_dim, action_dim)

# Initialize policy
policy = TD3.TD3(state_dim, action_dim, max_action)

#Load policy or model based on input
if args.policy_num:
    filename = "Policy_" + str(args.policy_num)
    directory = "./policies"
    policy.load(filename, directory)
else:
    filename = "TD3_" + args.model_num
    directory = "./pytorch_models"
    policy.load(filename, directory)

# Reset Env
done = False
state, info = env.reset()

total_reward = 0
total_reward_per_tile = 0
cte_list = []

num_sim = 1
for i in range(num_sim):
    
    #Simulation loop
    done = False
    while not done:
        # Select action
        action = policy.select_action(np.array(state))
        action = [action[0], 0, 0]

        # Perform action
        state, reward, terminated, truncated, info = env.step(action) 

        # account for cte 
        cte_list.append(state[1])

        # account for total rewards
        total_reward += reward
        
        if  terminated or truncated:
            # account rewardPerTile
            total_reward_per_tile += info["rewardPerTile"]

            # reset
            state, info = env.reset()

            done = True
        
print("Variance of CTE: ", np.var(cte_list)*1000)

print("Average reward: ", total_reward / num_sim)

print("Average tile reward: ", total_reward_per_tile / num_sim)
    



