import numpy as np
import random
from collections import namedtuple, deque

from model import QNetwork

import torch
import torch.nn.functional as F
import torch.optim as optim
import torch.nn as nn

BUFFER_SIZE = int(1e5)  # replay buffer size
BATCH_SIZE = 64         # minibatch size
GAMMA = 0.99            # discount factor
TAU = 1e-3              # for soft update of target parameters
LR = 5e-4               # learning rate 
UPDATE_EVERY = 4        # how often to update the network

device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

def get_device_info(dev=None):  
  if torch.cuda.is_available():
    if dev is None:
      dev = torch.device("cuda:0")
    if int(torch.__version__[0]) > 0:
      _dev = dev
    else:
      _dev = dev.index
    gpu = torch.cuda.get_device_properties(_dev)
    return gpu.name, gpu.total_memory / (1024**3), gpu.multi_processor_count
  else:
    return None, None, None

class Agent():
    """Interacts with and learns from the environment."""

    
    def __init__(self, state_size, action_size, seed, 
                 double_dqn=False, dueling=False):
        """Initialize an Agent object.
        
        Params
        ======
            state_size (int): dimension of each state
            action_size (int): dimension of each action
            seed (int): random seed
            double_dqn: use DDQN
            dueling: use adv/value stream split in model
        """
        self.state_size = state_size
        self.action_size = action_size
        self.double_dqn = double_dqn
        self.dueling = dueling
        self.seed = random.seed(seed)

        
        # Q-Network
        self.qnetwork_local = QNetwork(state_size, action_size, seed,
                                       dueling=self.dueling).to(device)
        print("Agent model:")
        print(self.qnetwork_local)
        var_device = next(self.qnetwork_local.denses.parameters()).device
        dev_name, _, _ = get_device_info(var_device)
        print(" Running on '{}':{}".format(var_device, dev_name))
        print(" Double DQN: '{}'".format(self.double_dqn))
        print(" Dueling DQN: '{}'".format(self.dueling))
        self.qnetwork_target = QNetwork(state_size, action_size, seed,
                                        dueling=self.dueling).to(device)
        self.optimizer = optim.Adam(self.qnetwork_local.parameters(), lr=LR)
        self.loss_func = nn.MSELoss()

        # Replay memory
        self.memory = ReplayBuffer(action_size, BUFFER_SIZE, BATCH_SIZE, seed)
        # Initialize time step (for updating every UPDATE_EVERY steps)
        self.t_step = 0
    
    def step(self, state, action, reward, next_state, done):
        # Save experience in replay memory
        self.memory.add(state, action, reward, next_state, done)
        
        # Learn every UPDATE_EVERY time steps.
        self.t_step = (self.t_step + 1) % UPDATE_EVERY
        if self.t_step == 0:
            # If enough samples are available in memory, get random subset and learn
            if len(self.memory) > BATCH_SIZE:
                experiences = self.memory.sample()
                self.learn(experiences, GAMMA)

    def act(self, state, eps=0.):
        """Returns actions for given state as per current policy.
        
        Params
        ======
            state (array_like): current state
            eps (float): epsilon, for epsilon-greedy action selection
        """
        state = torch.from_numpy(state).float().unsqueeze(0).to(device)
        self.qnetwork_local.eval()
        with torch.no_grad():
            action_values = self.qnetwork_local(state)
        self.qnetwork_local.train()

        # Epsilon-greedy action selection
        if random.random() > eps:
            return np.argmax(action_values.cpu().data.numpy())
        else:
            return random.choice(np.arange(self.action_size))

    def learn(self, experiences, gamma):
        """Update value parameters using given batch of experience tuples.

        Params
        ======
            experiences (Tuple[torch.Variable]): tuple of (s, a, r, s', done) tuples 
            gamma (float): discount factor
        """
        states, actions, rewards, next_states, dones = experiences                
                
        target_values = self.qnetwork_target(next_states).detach()
        
        if self.double_dqn:
            local_next_values = self.qnetwork_local(next_states)
            _, local_next_actions = torch.max(local_next_values, 1)
            local_next_actions = local_next_actions.detach().unsqueeze(1)
            next_max_values = torch.gather(target_values, 1, local_next_actions)
        else:
          next_max_values, next_best_actions = target_values.max(1)
          next_max_values = next_max_values.unsqueeze(1)
          
        targets = rewards + gamma * next_max_values * (1 - dones)
        
        outputs = self.qnetwork_local(states)
        
        selected_outputs = torch.gather(outputs, 1, actions)
        
        self.optimizer.zero_grad()
        loss = self.loss_func(selected_outputs, targets)
        loss.backward()
        self.optimizer.step()

        # ------------------- update target network ------------------- #
        self.soft_update(self.qnetwork_local, self.qnetwork_target, TAU)                     

    def soft_update(self, local_model, target_model, tau):
        """Soft update model parameters.
        θ_target = τ*θ_local + (1 - τ)*θ_target

        Params
        ======
            local_model (PyTorch model): weights will be copied from
            target_model (PyTorch model): weights will be copied to
            tau (float): interpolation parameter 
        """
        for target_param, local_param in zip(target_model.parameters(), local_model.parameters()):
            target_param.data.copy_(tau*local_param.data + (1.0-tau)*target_param.data)


class ReplayBuffer:
    """Fixed-size buffer to store experience tuples."""

    def __init__(self, action_size, buffer_size, batch_size, seed):
        """Initialize a ReplayBuffer object.

        Params
        ======
            action_size (int): dimension of each action
            buffer_size (int): maximum size of buffer
            batch_size (int): size of each training batch
            seed (int): random seed
        """
        self.action_size = action_size
        self.memory = deque(maxlen=buffer_size)  
        self.batch_size = batch_size
        self.experience = namedtuple("Experience", field_names=["state", "action", "reward", "next_state", "done"])
        self.seed = random.seed(seed)
    
    def add(self, state, action, reward, next_state, done):
        """Add a new experience to memory."""
        e = self.experience(state, action, reward, next_state, done)
        self.memory.append(e)
    
    def sample(self):
        """Randomly sample a batch of experiences from memory."""
        experiences = random.sample(self.memory, k=self.batch_size)

        states = torch.from_numpy(np.vstack([e.state for e in experiences if e is not None])).float().to(device)
        actions = torch.from_numpy(np.vstack([e.action for e in experiences if e is not None])).long().to(device)
        rewards = torch.from_numpy(np.vstack([e.reward for e in experiences if e is not None])).float().to(device)
        next_states = torch.from_numpy(np.vstack([e.next_state for e in experiences if e is not None])).float().to(device)
        dones = torch.from_numpy(np.vstack([e.done for e in experiences if e is not None]).astype(np.uint8)).float().to(device)
  
        return (states, actions, rewards, next_states, dones)

    def __len__(self):
        """Return the current size of internal memory."""
        return len(self.memory)