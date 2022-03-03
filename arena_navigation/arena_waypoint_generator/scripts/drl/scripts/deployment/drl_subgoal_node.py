#!/usr/bin/env python3
import os
import pickle
import rospy
import rospkg
import sys

from stable_baselines3 import PPO

from flatland_msgs.srv import StepWorld, StepWorldRequest
from rospy.exceptions import ROSException
from std_msgs.msg import Bool

from arena_navigation.arena_waypoint_generator.scripts.drl.rl_agent.envs import BaseDRLAgent

robot_model = rospy.get_param("model")
""" TEMPORARY GLOBAL CONSTANTS """
NS_PREFIX = ""
TRAINED_MODELS_DIR = os.path.join(
    rospkg.RosPack().get_path("arena_waypoint_generator"), "scripts/drl/agents"
)

class DeploymentDRLAgent(BaseDRLAgent):
    def __init__(
        self,
        agent_name: str,
        ns: str = None,
        robot_name: str = None,
        *args,
        **kwargs,
    ) -> None:
        self._is_train_mode = rospy.get_param("/train_mode")
        if not self._is_train_mode:
            rospy.init_node(f"DRL_subgoal", anonymous=True)

        self.name = agent_name

        hyperparameter_path = os.path.join(TRAINED_MODELS_DIR, self.name, "hyperparameters.json")
        super().__init__(
            ns,
            robot_name,
            hyperparameter_path,
        )
        self.setup_agent()
        if not self._is_train_mode:
            self._service_name_step = f"{self._ns}step_world"
            self._sim_step_client = rospy.ServiceProxy(
                self._service_name_step, StepWorld
            )

    def setup_agent(self) -> None:
        """Loads the trained policy and when required the VecNormalize object."""
        model_file = os.path.join(
            TRAINED_MODELS_DIR, self.name, "best_model.zip"
        )
        vecnorm_file = os.path.join(
            TRAINED_MODELS_DIR, self.name, "vec_normalize.pkl"
        )

        assert os.path.isfile(
            model_file
        ), f"Compressed model cannot be found at {model_file}!"

        if self._agent_params["normalize"]:
            assert os.path.isfile(
                vecnorm_file
            ), f"VecNormalize file cannot be found at {vecnorm_file}!"

            with open(vecnorm_file, "rb") as file_handler:
                vec_normalize = pickle.load(file_handler)
            self._obs_norm_func = vec_normalize.normalize_obs

        self._agent = PPO.load(model_file).policy

    def run(self) -> None:
        while not rospy.is_shutdown():
            if self._is_train_mode:
                self.call_service_takeSimStep(self._action_frequency)
            else:
                self._wait_for_next_action_cycle()
            obs = self.get_observations()[0]
            action = self.get_action(obs)
            self.publish_action(action)

    def _wait_for_next_action_cycle(self) -> None:
        try:
            rospy.wait_for_message(f"{self._ns_robot}next_cycle", Bool)
        except ROSException:
            pass

    def call_service_takeSimStep(self, t: float = None) -> None:
        request = StepWorldRequest() if t is None else StepWorldRequest(t)

        try:
            response = self._sim_step_client(request)
            rospy.logdebug("step service=", response)
        except rospy.ServiceException as e:
            rospy.logdebug("step Service call failed: %s" % e)


def main(agent_name: str) -> None:
    AGENT = DeploymentDRLAgent(agent_name=agent_name, ns=NS_PREFIX)

    try:
        AGENT.run()
    except rospy.ROSInterruptException:
        pass

AGENTS = [
    "MLP_ARENA2D_2021_12_04__15_36",
]

if __name__ == "__main__":
    #AGENT_NAME = sys.argv[1]
    AGENT_NAME = AGENTS[0]
    main(agent_name=AGENT_NAME)