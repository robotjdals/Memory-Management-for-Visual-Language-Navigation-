import json
from typing import Optional

import numpy as np
import rclpy
from PIL import Image
from rclpy.node import Node
from sensor_msgs.msg import Image as RosImage

from efficientnav_interfaces.srv import DetectObjects


def raw_image_to_pil(height: int, width: int, encoding: str, data: bytes) -> Image.Image:
    channels_by_encoding = {
        "rgb8": 3,
        "bgr8": 3,
        "rgba8": 4,
        "bgra8": 4,
        "mono8": 1,
    }
    if encoding not in channels_by_encoding:
        raise ValueError(f"Unsupported image encoding: {encoding}")

    channels = channels_by_encoding[encoding]
    array = np.frombuffer(data, dtype=np.uint8)
    array = array.reshape((height, width, channels))

    if encoding == "rgb8":
        return Image.fromarray(array, "RGB")
    if encoding == "bgr8":
        return Image.fromarray(array[:, :, ::-1], "RGB")
    if encoding == "rgba8":
        return Image.fromarray(array, "RGBA").convert("RGB")
    if encoding == "bgra8":
        return Image.fromarray(array[:, :, [2, 1, 0, 3]], "RGBA").convert("RGB")
    return Image.fromarray(array[:, :, 0], "L").convert("RGB")


def pil_to_ros_image(image: Image.Image, frame_id: str) -> RosImage:
    array = np.asarray(image.convert("RGB"))
    msg = RosImage()
    msg.header.frame_id = frame_id
    msg.height = array.shape[0]
    msg.width = array.shape[1]
    msg.encoding = "rgb8"
    msg.is_bigendian = False
    msg.step = msg.width * 3
    msg.data = array.tobytes()
    return msg


class EfficientNavDetectionNode(Node):
    def __init__(self) -> None:
        super().__init__("efficientnav_detection_node")
        print("[efficientnav_detection] node initialization started", flush=True)

        self.declare_parameter(
            "config_file",
            "/home/min/DINO_ws/GroundingDINO/groundingdino/config/GroundingDINO_SwinT_OGC.py",
        )
        self.declare_parameter(
            "checkpoint_path",
            "/home/min/DINO_ws/GroundingDINO/weights/groundingdino_swint_ogc.pth",
        )
        self.declare_parameter("box_threshold", 0.5)
        self.declare_parameter("text_threshold", 0.25)
        self.declare_parameter("cpu_only", False)
        self.declare_parameter("service_name", "/detection/detect_objects")
        self.declare_parameter("annotated_image_topic", "/detection/image")

        config_file = self.get_parameter("config_file").get_parameter_value().string_value
        checkpoint_path = self.get_parameter("checkpoint_path").get_parameter_value().string_value
        box_threshold = self.get_parameter("box_threshold").get_parameter_value().double_value
        text_threshold = self.get_parameter("text_threshold").get_parameter_value().double_value
        cpu_only = self.get_parameter("cpu_only").get_parameter_value().bool_value

        print("[efficientnav_detection] importing GroundingDINO wrapper", flush=True)
        from .dino_utils import GroundingDinoDetector

        print(
            "[efficientnav_detection] loading GroundingDINO model "
            f"(config={config_file}, checkpoint={checkpoint_path}, cpu_only={cpu_only})",
            flush=True,
        )
        self.detector = GroundingDinoDetector(
            config_file=config_file,
            checkpoint_path=checkpoint_path,
            box_threshold=box_threshold,
            text_threshold=text_threshold,
            cpu_only=cpu_only,
        )
        print("[efficientnav_detection] GroundingDINO model loaded", flush=True)

        annotated_image_topic = self.get_parameter("annotated_image_topic").get_parameter_value().string_value
        service_name = self.get_parameter("service_name").get_parameter_value().string_value

        self.annotated_pub = self.create_publisher(RosImage, annotated_image_topic, 10)
        self.create_service(DetectObjects, service_name, self.detect_objects_callback)

        print("[efficientnav_detection] ROS2 service/publishers ready", flush=True)
        self.get_logger().info("EfficientNav detection node is ready.")

    def detect_objects_callback(self, request: DetectObjects.Request, response: DetectObjects.Response):
        request_id = f"{request.position_id}:{request.angle}"
        prompt = request.prompt.strip()
        self.get_logger().info(
            f"Request received: request_id={request_id}, position_id={request.position_id}, "
            f"angle={request.angle}, prompt={prompt}"
        )

        if not prompt:
            response.result_json = json.dumps(
                {
                    "position_id": request.position_id,
                    "angle": int(request.angle),
                    "prompt": prompt,
                    "detections": [],
                    "error": "empty_prompt",
                },
                ensure_ascii=True,
            )
            self.get_logger().warning(f"Skipping request because prompt is empty: request_id={request_id}")
            return response

        try:
            self.get_logger().info(
                f"Detection start: request_id={request_id}, height={request.height}, width={request.width}"
            )
            image_pil = raw_image_to_pil(
                int(request.height),
                int(request.width),
                request.encoding,
                bytes(request.data),
            )
            detections, annotated = self.detector.detect(image_pil, prompt)
            self.get_logger().info(
                f"Detection done: request_id={request_id}, detections={len(detections)}"
            )
        except Exception as exc:
            self.get_logger().error(f"Detection failed: request_id={request_id}, error={exc}")
            response.result_json = json.dumps(
                {
                    "position_id": request.position_id,
                    "angle": int(request.angle),
                    "prompt": prompt,
                    "detections": [],
                    "error": str(exc),
                },
                ensure_ascii=True,
            )
            return response

        payload = {
            "prompt": prompt,
            "position_id": request.position_id,
            "angle": int(request.angle),
            "detections": [item.to_dict() for item in detections],
        }
        response.result_json = json.dumps(payload, ensure_ascii=True)
        self.get_logger().info(
            f"Response ready: request_id={request_id}, detections={len(detections)}"
        )

        annotated_msg = pil_to_ros_image(annotated, "camera_link")
        self.annotated_pub.publish(annotated_msg)
        return response


def main(args: Optional[list] = None) -> None:
    print("[efficientnav_detection] main started", flush=True)
    rclpy.init(args=args)
    print("[efficientnav_detection] rclpy initialized", flush=True)
    node = EfficientNavDetectionNode()
    try:
        print("[efficientnav_detection] entering spin", flush=True)
        rclpy.spin(node)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
