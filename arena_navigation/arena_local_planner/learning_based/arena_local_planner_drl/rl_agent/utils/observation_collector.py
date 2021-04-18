#! /usr/bin/env python
from typing import Tuple

from datetime import datetime

from numpy.core.numeric import normalize_axis_tuple
import rospy
import random
import numpy as np

import time # for debuging

# observation msgs
from sensor_msgs.msg import LaserScan
from geometry_msgs.msg import Pose2D,PoseStamped, PoseWithCovarianceStamped
from geometry_msgs.msg import Twist
from arena_plan_msgs.msg import RobotState,RobotStateStamped

# services
from flatland_msgs.srv import StepWorld,StepWorldRequest


# message filter
import message_filters

# for transformations
from tf.transformations import *

from gym import spaces
import numpy as np




class ObservationCollector():
    def __init__(self,num_lidar_beams:int,lidar_range:float):
        """ a class to collect and merge observations

        Args:
            num_lidar_beams (int): [description]
            lidar_range (float): [description]
        """
       
        """#TODO this is the original Flatland observation space add a switch
        # define observation_space
        self.observation_space = ObservationCollector._stack_spaces((
            spaces.Box(low=0, high=lidar_range, shape=(num_lidar_beams,), dtype=np.float32),
            spaces.Box(low=0, high=10, shape=(1,), dtype=np.float32) ,
            spaces.Box(low=-np.pi, high=np.pi, shape=(1,), dtype=np.float32) 
        ))
        """

        #TODO this is the observation_space for Jiuyun's environment
        self._current_reward = 0
        # define observation_space (for Jiayun's IL environment)
        self.observation_space = ObservationCollector._stack_spaces((
            spaces.Box(low=0, high=lidar_range, shape=(num_lidar_beams,), dtype=np.float32),
            spaces.Box(low=-5, high=30, shape=(1,), dtype=np.float32) ,
            spaces.Box(low=-5, high=25, shape=(1,), dtype=np.float32) ,
            spaces.Box(low=-np.pi, high=np.pi, shape=(1,), dtype=np.float32),
	        spaces.Box(low=np.array([-5, -5]), high=np.array([30, 25]), dtype=np.float32),
            spaces.Box(low=-10, high=15, shape=(1,), dtype=np.float32)
        ))

        # flag of new sensor info
        self._flag_all_received=False

        self._scan = LaserScan()
        self._robot_pose = Pose2D()
        self._robot_vel = Twist()
        self._subgoal =  Pose2D()
        self._cmd_vel = Twist()
        

        # message_filter subscriber: laserscan, robot_pose
        self._scan_sub = message_filters.Subscriber("scan", LaserScan)
        self._robot_state_sub = message_filters.Subscriber('plan_manager/robot_state', RobotStateStamped)

        # command velocity subscriber
        self._cmd_vel_sub = message_filters.Subscriber('cmd_vel', Twist)
        
        # message_filters.TimeSynchronizer: call callback only when all sensor info are ready
        #self.ts = message_filters.ApproximateTimeSynchronizer([self._scan_sub, self._robot_state_sub], 100,slop=0.05) #without synchronizing cmd_vel
        self.ts = message_filters.ApproximateTimeSynchronizer([self._scan_sub, self._robot_state_sub, self._cmd_vel_sub], 100,slop=0.05,allow_headerless=True)
        self.ts.registerCallback(self.callback_observation_received)
        
        # topic subscriber: subgoal
        #TODO should we synchoronize it with other topics
        self._subgoal_sub = message_filters.Subscriber('move_base_simple/goal', PoseStamped)
        self._subgoal_sub.registerCallback(self.callback_subgoal)
        
        # service clients
        self._is_train_mode = rospy.get_param("train_mode")
        if self._is_train_mode:
            self._service_name_step='step_world'
            self._sim_step_client = rospy.ServiceProxy(self._service_name_step, StepWorld)


    
    def get_observation_space(self):
        return self.observation_space

    def get_observations_and_action(self):
        # Get synchronized observations and return them along with the current command velocity (action).
        # Since get_observations() is the only function called in record_rollouts.py that calls the step_world service,
        # the cmd_vel (action) will still be synchronized with the observations
        merged_obs, obs_dict = self.get_observations()
        action = self._cmd_vel
        # action.linear.x and action.angular.z are the only non-zero values and are python floats.
        action = np.array([action.linear.x, action.angular.z])
        return merged_obs, obs_dict, action
    
    def get_observations(self):
        # reset flag 
        self._flag_all_received=False
        if self._is_train_mode: 
        # sim a step forward until all sensor msg uptodate
            i=0
            while(self._flag_all_received==False):
                self.call_service_takeSimStep()
                #print(f"waiting for synched observations: {i}")  # for debugging only
                i+=1
        # rospy.logdebug(f"Current observation takes {i} steps for Synchronization")
        #print(f"Current observation takes {i} steps for Synchronization")
        
        scan=self._scan.ranges.astype(np.float32)
        rho, theta = ObservationCollector._get_goal_pose_in_robot_frame(self._subgoal,self._robot_pose)

        """#TODO merged_obs from original Flatlandenv. add a switch
        merged_obs = np.hstack([scan, np.array([rho,theta])])
        """

        #TODO merged_obs for Jiayun's IL environment:
        rob_x, rob_y, rob_theta = self._robot_pose.x, self._robot_pose.y, self._robot_pose.theta
        goal_x, goal_y = self._subgoal.x, self._subgoal.y
        #merged_obs = np.hstack([scan, np.array([rho,theta])])
        merged_obs = np.hstack([scan, np.array([rob_x, rob_y, rob_theta, goal_x, goal_y, self._current_reward])])
        #merged_obs = np.hstack([scan, np.array([rob_x, rob_y, rob_theta, goal_x, goal_y])])
        # </>merged_obs for Jiayun's IL environment

        obs_dict = {}
        obs_dict["laser_scan"] = scan
        obs_dict['goal_in_robot_frame'] = [rho,theta]
        return merged_obs, obs_dict
    
    @staticmethod
    def _get_goal_pose_in_robot_frame(goal_pos:Pose2D,robot_pos:Pose2D):
         y_relative = goal_pos.y - robot_pos.y
         x_relative = goal_pos.x - robot_pos.x
         rho =  (x_relative**2+y_relative**2)**0.5
         theta = (np.arctan2(y_relative,x_relative)-robot_pos.theta+4*np.pi)%(2*np.pi)-np.pi
         return rho,theta


    def call_service_takeSimStep(self):
        request=StepWorldRequest()
        try:
            response=self._sim_step_client(request)
            rospy.logdebug("step service=",response)
        except rospy.ServiceException as e:
            rospy.logdebug("step Service call failed: %s"%e)

    def callback_subgoal(self,msg_Subgoal):
        self._subgoal=self.process_subgoal_msg(msg_Subgoal)
        
        return


    def callback_observation_received(self,msg_LaserScan,msg_RobotStateStamped, msg_cmd_vel):
        self._cmd_vel = msg_cmd_vel
        
        # process sensor msg
        self._scan=self.process_scan_msg(msg_LaserScan)
        self._robot_pose,self._robot_vel=self.process_robot_state_msg(msg_RobotStateStamped)

        # ask subgoal service
        #self._subgoal=self.call_service_askForSubgoal()
        self._flag_all_received=True
        
    def process_scan_msg(self, msg_LaserScan):
        # remove_nans_from_scan
        scan = np.array(msg_LaserScan.ranges)
        scan[np.isnan(scan)] = msg_LaserScan.range_max
        msg_LaserScan.ranges = scan
        return msg_LaserScan
    
    def process_robot_state_msg(self,msg_RobotStateStamped):
        state=msg_RobotStateStamped.state
        pose3d=state.pose
        twist=state.twist
        return self.pose3D_to_pose2D(pose3d), twist
        
    def process_pose_msg(self,msg_PoseWithCovarianceStamped):
        # remove Covariance
        pose_with_cov=msg_PoseWithCovarianceStamped.pose
        pose=pose_with_cov.pose
        return self.pose3D_to_pose2D(pose)
    
    def process_subgoal_msg(self,msg_Subgoal):
        pose2d=self.pose3D_to_pose2D(msg_Subgoal.pose)
        return pose2d

    @staticmethod
    def pose3D_to_pose2D(pose3d):
        pose2d=Pose2D()
        pose2d.x=pose3d.position.x
        pose2d.y=pose3d.position.y
        quaternion=(pose3d.orientation.x,pose3d.orientation.y,pose3d.orientation.z,pose3d.orientation.w)
        euler = euler_from_quaternion(quaternion)
        yaw = euler[2]
        pose2d.theta=yaw
        return pose2d
    @staticmethod
    def _stack_spaces(ss:Tuple[spaces.Box]):
        low = []
        high = []
        for space in ss:
            low.extend(space.low.tolist())
            high.extend(space.high.tolist())
        return spaces.Box(np.array(low).flatten(),np.array(high).flatten())
    
    #TODO for Jiayun's IL environment
    def register_reward(self, reward):
        self._current_reward = reward




if __name__ == '__main__':
    
    rospy.init_node('states', anonymous=True)
    print("start")

    state_collector=ObservationCollector(360,10)
    i=0
    r=rospy.Rate(100)
    while(i<=100):
        i=i+1
        print(i)
        obs=state_collector.get_observations()
        print(obs)
        
        time.sleep(0.001)
        


    



