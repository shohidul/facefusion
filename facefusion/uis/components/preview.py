import os
import shutil
import subprocess
from time import sleep
from typing import Any, List, Optional, Tuple

import cv2
import gradio
import numpy

from facefusion import logger, process_manager, state_manager, translator
from facefusion.audio import create_empty_audio_frame, get_voice_frame
from facefusion.common_helper import get_first, get_middle
from facefusion.content_analyser import analyse_frame
from facefusion.face_creator import get_one_face
from facefusion.face_selector import select_faces
from facefusion.face_store import clear_faces
from facefusion.filesystem import filter_audio_paths, is_image, is_video, normalize_filename
from facefusion.processors.core import get_processors_modules
from facefusion.types import AudioFrame, Face, Mask, VisionFrame
from facefusion.uis import choices as uis_choices
from facefusion.uis.core import get_ui_component, get_ui_components, register_ui_component
from facefusion.uis.types import ComponentOptions, PreviewMode
from facefusion.vision import detect_frame_orientation, extract_vision_mask, fit_cover_frame, is_vision_frame, merge_vision_mask, obscure_frame, read_static_image, read_static_images, read_video_frame, restrict_frame, select_video_frames, unpack_resolution, write_image

PREVIEW_IMAGE : Optional[gradio.Image] = None
SAVE_PREVIEW_TO_TARGET_BUTTON : Optional[gradio.Button] = None
BATCH_SAVE_PREVIEWS_BUTTON : Optional[gradio.Button] = None
ORIGINAL_TARGET_FRAMES : dict[str, VisionFrame] = {}


def get_original_target_frame(target_path : str) -> Optional[VisionFrame]:
	if not target_path or is_video(target_path):
		return None
	filename = os.path.basename(target_path)
	norm_name = normalize_filename(filename)

	if target_path in ORIGINAL_TARGET_FRAMES:
		return ORIGINAL_TARGET_FRAMES[target_path].copy()
	if filename in ORIGINAL_TARGET_FRAMES:
		return ORIGINAL_TARGET_FRAMES[filename].copy()
	for k, v in ORIGINAL_TARGET_FRAMES.items():
		if normalize_filename(os.path.basename(k)) == norm_name:
			return v.copy()

	frame = read_static_image(target_path, 'rgba')
	if is_vision_frame(frame):
		ORIGINAL_TARGET_FRAMES[target_path] = frame.copy()
		ORIGINAL_TARGET_FRAMES[filename] = frame.copy()
		return frame.copy()
	return None


def register_original_target_frame(target_path : str, frame : Optional[VisionFrame] = None, force : bool = False) -> None:
	if not target_path or is_video(target_path):
		return
	filename = os.path.basename(target_path)
	norm_name = normalize_filename(filename)
	if not force:
		if target_path in ORIGINAL_TARGET_FRAMES or filename in ORIGINAL_TARGET_FRAMES:
			return
		for k in ORIGINAL_TARGET_FRAMES.keys():
			if normalize_filename(os.path.basename(k)) == norm_name:
				return

	if not is_vision_frame(frame):
		frame = read_static_image(target_path, 'rgba')
	if is_vision_frame(frame):
		ORIGINAL_TARGET_FRAMES[target_path] = frame.copy()
		ORIGINAL_TARGET_FRAMES[filename] = frame.copy()


def render() -> None:
	global PREVIEW_IMAGE
	global SAVE_PREVIEW_TO_TARGET_BUTTON
	global BATCH_SAVE_PREVIEWS_BUTTON

	preview_image_options : ComponentOptions =\
	{
		'label': translator.get('uis.preview_image'),
		'show_download_button': True,
		'interactive': False
	}

	source_vision_frames = read_static_images(state_manager.get_item('source_paths'))
	source_audio_path = get_first(filter_audio_paths(state_manager.get_item('source_paths')))
	source_audio_frame = create_empty_audio_frame()
	source_voice_frame = create_empty_audio_frame()

	if source_audio_path and state_manager.get_item('output_video_fps'):
		temp_voice_frame = get_voice_frame(source_audio_path, state_manager.get_item('output_video_fps'), state_manager.get_item('reference_frame_number'))
		if numpy.any(temp_voice_frame):
			source_voice_frame = temp_voice_frame

	if is_image(state_manager.get_item('target_path')):
		target_vision_frame = read_static_image(state_manager.get_item('target_path'))
		reference_vision_frame = read_static_image(state_manager.get_item('target_path'))
		preview_vision_frame = process_preview_frame(reference_vision_frame, source_vision_frames, source_audio_frame, source_voice_frame, [ target_vision_frame ], uis_choices.preview_modes[0], uis_choices.preview_resolutions[-1])
		preview_image_options['value'] = cv2.cvtColor(preview_vision_frame, cv2.COLOR_BGR2RGB)
		preview_image_options['elem_classes'] = [ 'image-preview', 'is-' + detect_frame_orientation(preview_vision_frame) ]

	if is_video(state_manager.get_item('target_path')):
		reference_vision_frame = read_video_frame(state_manager.get_item('target_path'), state_manager.get_item('reference_frame_number'))
		target_vision_frames = select_video_frames(state_manager.get_item('target_path'), state_manager.get_item('reference_frame_number'), state_manager.get_item('target_frame_amount'))
		preview_vision_frame = process_preview_frame(reference_vision_frame, source_vision_frames, source_audio_frame, source_voice_frame, target_vision_frames, uis_choices.preview_modes[0], uis_choices.preview_resolutions[-1])
		preview_image_options['value'] = cv2.cvtColor(preview_vision_frame, cv2.COLOR_BGR2RGB)
		preview_image_options['elem_classes'] = [ 'image-preview', 'is-' + detect_frame_orientation(preview_vision_frame) ]
		preview_image_options['visible'] = True

	with gradio.Group(elem_classes = [ 'preview-group' ]):
		PREVIEW_IMAGE = gradio.Image(**preview_image_options)
		SAVE_PREVIEW_TO_TARGET_BUTTON = gradio.Button(
			'💾 Save Preview to Target (Replace on Disk)',
			size = 'sm',
			variant = 'primary',
			elem_classes = [ 'save-preview-button' ]
		)
		BATCH_SAVE_PREVIEWS_BUTTON = gradio.Button(
			'⚡ Batch Replace All Uploaded Targets',
			size = 'sm',
			variant = 'secondary',
			elem_classes = [ 'batch-save-preview-button' ]
		)
	register_ui_component('preview_image', PREVIEW_IMAGE)
	register_ui_component('save_preview_to_target_button', SAVE_PREVIEW_TO_TARGET_BUTTON)
	register_ui_component('batch_save_preview_button', BATCH_SAVE_PREVIEWS_BUTTON)


def listen() -> None:
	preview_frame_slider = get_ui_component('preview_frame_slider')
	preview_mode_dropdown = get_ui_component('preview_mode_dropdown')
	preview_resolution_dropdown = get_ui_component('preview_resolution_dropdown')

	if preview_mode_dropdown:
		preview_mode_dropdown.change(preview_mode_change_and_update_preview, inputs = [ preview_mode_dropdown, preview_resolution_dropdown, preview_frame_slider ], outputs = PREVIEW_IMAGE)

	if preview_resolution_dropdown:
		preview_resolution_dropdown.change(update_preview_image, inputs = [ preview_mode_dropdown, preview_resolution_dropdown, preview_frame_slider ], outputs = PREVIEW_IMAGE)

	if preview_frame_slider:
		preview_frame_slider.release(update_preview_image, inputs = [ preview_mode_dropdown, preview_resolution_dropdown, preview_frame_slider ], outputs = PREVIEW_IMAGE, show_progress = 'hidden')
		preview_frame_slider.change(update_preview_image, inputs = [ preview_mode_dropdown, preview_resolution_dropdown, preview_frame_slider ], outputs = PREVIEW_IMAGE, show_progress = 'hidden', trigger_mode = 'once')

	reference_face_position_gallery = get_ui_component('reference_face_position_gallery')
	if reference_face_position_gallery:
		ref_outputs = [ PREVIEW_IMAGE ]
		if SAVE_PREVIEW_TO_TARGET_BUTTON:
			ref_outputs.append(SAVE_PREVIEW_TO_TARGET_BUTTON)
		if BATCH_SAVE_PREVIEWS_BUTTON:
			ref_outputs.append(BATCH_SAVE_PREVIEWS_BUTTON)
		reference_face_position_gallery.select(select_reference_face_and_update_preview, inputs = [ preview_mode_dropdown, preview_resolution_dropdown, preview_frame_slider ], outputs = ref_outputs)

	preview_outputs = [ PREVIEW_IMAGE ]
	if SAVE_PREVIEW_TO_TARGET_BUTTON:
		preview_outputs.append(SAVE_PREVIEW_TO_TARGET_BUTTON)
	if BATCH_SAVE_PREVIEWS_BUTTON:
		preview_outputs.append(BATCH_SAVE_PREVIEWS_BUTTON)

	for ui_component in get_ui_components(
	[
		'source_audio',
		'source_image',
		'target_video'
	]):
		for method in [ 'change', 'clear' ]:
			getattr(ui_component, method)(clear_and_update_preview_image, inputs = [ preview_mode_dropdown, preview_resolution_dropdown, preview_frame_slider ], outputs = preview_outputs)

	target_image = get_ui_component('target_image')
	if target_image:
		t_outputs = [ PREVIEW_IMAGE ]
		if SAVE_PREVIEW_TO_TARGET_BUTTON:
			t_outputs.append(SAVE_PREVIEW_TO_TARGET_BUTTON)
		if BATCH_SAVE_PREVIEWS_BUTTON:
			t_outputs.append(BATCH_SAVE_PREVIEWS_BUTTON)
		target_image.change(target_change_preview_update, inputs = [ preview_mode_dropdown, preview_resolution_dropdown, preview_frame_slider ], outputs = t_outputs)
		target_image.clear(target_clear_preview_update, inputs = [ preview_mode_dropdown, preview_resolution_dropdown, preview_frame_slider ], outputs = t_outputs)

	if SAVE_PREVIEW_TO_TARGET_BUTTON:
		outputs = [ SAVE_PREVIEW_TO_TARGET_BUTTON, PREVIEW_IMAGE ]
		if reference_face_position_gallery:
			outputs.append(reference_face_position_gallery)
		SAVE_PREVIEW_TO_TARGET_BUTTON.click(save_preview_to_target, outputs = outputs)

	if BATCH_SAVE_PREVIEWS_BUTTON:
		batch_outputs = [ BATCH_SAVE_PREVIEWS_BUTTON, PREVIEW_IMAGE ]
		if reference_face_position_gallery:
			batch_outputs.append(reference_face_position_gallery)
		BATCH_SAVE_PREVIEWS_BUTTON.click(batch_save_previews_to_targets, outputs = batch_outputs)

	for ui_component in get_ui_components(
	[
		'background_remover_fill_color_red_number',
		'background_remover_fill_color_green_number',
		'background_remover_fill_color_blue_number',
		'background_remover_fill_color_alpha_number',
		'background_remover_despill_color_red_number',
		'background_remover_despill_color_green_number',
		'background_remover_despill_color_blue_number',
		'background_remover_despill_color_alpha_number',
		'face_debugger_items_checkbox_group',
		'frame_colorizer_size_dropdown',
		'face_mask_types_checkbox_group',
		'face_mask_areas_checkbox_group',
		'face_mask_regions_checkbox_group',
		'expression_restorer_areas_checkbox_group'
	]):
		ui_component.change(update_preview_image, inputs = [ preview_mode_dropdown, preview_resolution_dropdown, preview_frame_slider ], outputs = PREVIEW_IMAGE)

	for ui_component in get_ui_components(
	[
		'age_modifier_direction_slider',
		'deep_swapper_morph_slider',
		'expression_restorer_factor_slider',
		'face_editor_eyebrow_direction_slider',
		'face_editor_eye_gaze_horizontal_slider',
		'face_editor_eye_gaze_vertical_slider',
		'face_editor_eye_open_ratio_slider',
		'face_editor_lip_open_ratio_slider',
		'face_editor_mouth_grim_slider',
		'face_editor_mouth_pout_slider',
		'face_editor_mouth_purse_slider',
		'face_editor_mouth_smile_slider',
		'face_editor_mouth_position_horizontal_slider',
		'face_editor_mouth_position_vertical_slider',
		'face_editor_head_pitch_slider',
		'face_editor_head_yaw_slider',
		'face_editor_head_roll_slider',
		'face_enhancer_blend_slider',
		'face_enhancer_weight_slider',
		'face_swapper_weight_slider',
		'frame_colorizer_blend_slider',
		'frame_enhancer_blend_slider',
		'lip_syncer_weight_slider',
		'reference_face_distance_slider',
		'face_selector_age_range_slider',
		'face_tracker_score_slider',
		'face_mask_blur_slider',
		'face_mask_padding_top_slider',
		'face_mask_padding_bottom_slider',
		'face_mask_padding_left_slider',
		'face_mask_padding_right_slider',
		'output_video_fps_slider'
	]):
		ui_component.release(update_preview_image, inputs = [ preview_mode_dropdown, preview_resolution_dropdown, preview_frame_slider ], outputs = PREVIEW_IMAGE)

	for ui_component in get_ui_components(
	[
		'age_modifier_model_dropdown',
		'background_remover_model_dropdown',
		'deep_swapper_model_dropdown',
		'expression_restorer_model_dropdown',
		'processors_checkbox_group',
		'face_editor_model_dropdown',
		'face_enhancer_model_dropdown',
		'face_swapper_model_dropdown',
		'face_swapper_pixel_boost_dropdown',
		'frame_colorizer_model_dropdown',
		'frame_enhancer_model_dropdown',
		'lip_syncer_model_dropdown',
		'face_selector_mode_dropdown',
		'face_selector_order_dropdown',
		'face_selector_gender_dropdown',
		'face_selector_race_dropdown',
		'face_detector_model_dropdown',
		'face_detector_size_dropdown',
		'face_detector_angles_checkbox_group',
		'face_landmarker_model_dropdown',
		'face_occluder_model_dropdown',
		'face_parser_model_dropdown',
		'voice_extractor_model_dropdown'
	]):
		ui_component.change(clear_and_update_preview_image, inputs = [ preview_mode_dropdown, preview_resolution_dropdown, preview_frame_slider ], outputs = preview_outputs)

	for ui_component in get_ui_components(
	[
		'face_detector_margin_slider',
		'face_detector_score_slider',
		'face_landmarker_score_slider'
	]):
		ui_component.release(clear_and_update_preview_image, inputs = [ preview_mode_dropdown, preview_resolution_dropdown, preview_frame_slider ], outputs = preview_outputs)


def update_preview_image(preview_mode : PreviewMode, preview_resolution : str, frame_number : int = 0) -> gradio.Image:
	while process_manager.is_checking():
		sleep(0.5)

	source_vision_frames = read_static_images(state_manager.get_item('source_paths'))
	source_audio_path = get_first(filter_audio_paths(state_manager.get_item('source_paths')))
	source_audio_frame = create_empty_audio_frame()
	source_voice_frame = create_empty_audio_frame()

	if source_audio_path and state_manager.get_item('output_video_fps'):
		audio_frame_number = frame_number
		if state_manager.get_item('trim_frame_start'):
			audio_frame_number -= state_manager.get_item('trim_frame_start')
		temp_voice_frame = get_voice_frame(source_audio_path, state_manager.get_item('output_video_fps'), audio_frame_number)
		if numpy.any(temp_voice_frame):
			source_voice_frame = temp_voice_frame

	if is_image(state_manager.get_item('target_path')):
		reference_vision_frame = read_static_image(state_manager.get_item('target_path'))
		target_vision_frame = read_static_image(state_manager.get_item('target_path'), 'rgba')
		preview_vision_frame = process_preview_frame(reference_vision_frame, source_vision_frames, source_audio_frame, source_voice_frame, [ target_vision_frame ], preview_mode, preview_resolution)
		preview_vision_frame = cv2.cvtColor(preview_vision_frame, cv2.COLOR_BGRA2RGBA)
		return gradio.Image(value = preview_vision_frame, elem_classes = [ 'image-preview', 'is-' + detect_frame_orientation(preview_vision_frame) ])

	if is_video(state_manager.get_item('target_path')):
		reference_vision_frame = read_video_frame(state_manager.get_item('target_path'), state_manager.get_item('reference_frame_number'))
		target_vision_frames = select_video_frames(state_manager.get_item('target_path'), frame_number, state_manager.get_item('target_frame_amount'))
		preview_vision_frame = process_preview_frame(reference_vision_frame, source_vision_frames, source_audio_frame, source_voice_frame, target_vision_frames, preview_mode, preview_resolution)
		preview_vision_frame = cv2.cvtColor(preview_vision_frame, cv2.COLOR_BGRA2RGBA)
		return gradio.Image(value = preview_vision_frame, elem_classes = [ 'image-preview', 'is-' + detect_frame_orientation(preview_vision_frame) ])
	return gradio.Image(value = None, elem_classes = None)


HOLD_PREVIEW_FRAME : Optional[VisionFrame] = None


def clear_hold_preview_frame() -> None:
	global HOLD_PREVIEW_FRAME
	HOLD_PREVIEW_FRAME = None


def set_hold_preview_frame(frame : VisionFrame) -> None:
	global HOLD_PREVIEW_FRAME
	HOLD_PREVIEW_FRAME = frame.copy()


def get_button_resets() -> List[gradio.Button]:
	resets = []
	if SAVE_PREVIEW_TO_TARGET_BUTTON:
		resets.append(gradio.Button(value = '💾 Save Preview to Target (Replace on Disk)'))
	if BATCH_SAVE_PREVIEWS_BUTTON:
		resets.append(gradio.Button(value = '⚡ Batch Replace All Uploaded Targets'))
	return resets


def target_change_preview_update(preview_mode : PreviewMode, preview_resolution : str, frame_number : int = 0) -> Any:
	global HOLD_PREVIEW_FRAME
	resets = get_button_resets()
	if HOLD_PREVIEW_FRAME is not None:
		img = gradio.Image(value = HOLD_PREVIEW_FRAME, elem_classes = [ 'image-preview', 'is-' + detect_frame_orientation(HOLD_PREVIEW_FRAME) ])
	else:
		clear_faces()
		img = update_preview_image(preview_mode, preview_resolution, frame_number)
	return (img, *resets) if resets else img


def target_clear_preview_update(preview_mode : PreviewMode, preview_resolution : str, frame_number : int = 0) -> Any:
	clear_faces()
	clear_hold_preview_frame()
	resets = get_button_resets()
	img = update_preview_image(preview_mode, preview_resolution, frame_number)
	return (img, *resets) if resets else img


def select_reference_face_and_update_preview(preview_mode : PreviewMode, preview_resolution : str, frame_number : int = 0, *args : Any, **kwargs : Any) -> Any:
	clear_hold_preview_frame()
	clear_faces()
	resets = get_button_resets()
	img = update_preview_image(preview_mode, preview_resolution, frame_number)
	return (img, *resets) if resets else img


def preview_mode_change_and_update_preview(preview_mode : PreviewMode, preview_resolution : str, frame_number : int = 0) -> gradio.Image:
	clear_hold_preview_frame()
	clear_faces()
	return update_preview_image(preview_mode, preview_resolution, frame_number)


def clear_and_update_preview_image(preview_mode : PreviewMode, preview_resolution : str, frame_number : int = 0, *args : Any, **kwargs : Any) -> Any:
	clear_faces()
	img = update_preview_image(preview_mode, preview_resolution, frame_number)
	resets = get_button_resets()
	return (img, *resets) if resets else img


def process_preview_frame(reference_vision_frame : VisionFrame, source_vision_frames : List[VisionFrame], source_audio_frame : AudioFrame, source_voice_frame : AudioFrame, target_vision_frames : List[VisionFrame], preview_mode : PreviewMode, preview_resolution : str) -> VisionFrame:
	target_vision_frame = get_middle(target_vision_frames)
	target_vision_frame = restrict_frame(target_vision_frame, unpack_resolution(preview_resolution))
	temp_vision_mask = extract_vision_mask(target_vision_frame)
	target_vision_frame = merge_vision_mask(target_vision_frame, temp_vision_mask)
	target_vision_frames = [ restrict_frame(vision_frame, unpack_resolution(preview_resolution))[:, :, :3] for vision_frame in target_vision_frames ]
	temp_vision_frame = target_vision_frame.copy()

	original_frame = get_original_target_frame(state_manager.get_item('target_path'))
	if is_vision_frame(original_frame):
		original_target_vision_frame = restrict_frame(original_frame, unpack_resolution(preview_resolution))
		orig_mask = extract_vision_mask(original_target_vision_frame)
		original_target_vision_frame = merge_vision_mask(original_target_vision_frame, orig_mask)
	else:
		original_target_vision_frame = target_vision_frame

	if analyse_frame(target_vision_frame[:, :, :3]):
		if preview_mode == 'frame-by-frame':
			orig_obscured = obscure_frame(original_target_vision_frame[:, :, :3])
			temp_vision_frame = obscure_frame(temp_vision_frame[:, :, :3])
			return numpy.hstack((orig_obscured, temp_vision_frame))

		if preview_mode == 'face-by-face':
			target_crop_vision_frame, output_crop_vision_frame = create_face_by_face(reference_vision_frame, source_vision_frames, original_target_vision_frame[:, :, :3], temp_vision_frame[:, :, :3])
			target_crop_vision_frame = obscure_frame(target_crop_vision_frame)
			output_crop_vision_frame = obscure_frame(output_crop_vision_frame)
			return numpy.hstack((target_crop_vision_frame, output_crop_vision_frame))

		temp_vision_frame = obscure_frame(temp_vision_frame)
		return temp_vision_frame

	for processor_module in get_processors_modules(state_manager.get_item('processors')):
		logger.disable()
		if processor_module.pre_process('preview'):
			logger.enable()
			temp_vision_frame, temp_vision_mask = processor_module.process_frame(
			{
				'reference_vision_frame': reference_vision_frame,
				'source_audio_frame': source_audio_frame,
				'source_voice_frame': source_voice_frame,
				'source_vision_frames': source_vision_frames,
				'target_vision_frames': target_vision_frames,
				'temp_vision_frame': temp_vision_frame[:, :, :3],
				'temp_vision_mask': temp_vision_mask
			})
		logger.enable()

	temp_vision_frame = prepare_output_frame(target_vision_frame, temp_vision_frame, temp_vision_mask)

	if preview_mode == 'frame-by-frame':
		return numpy.hstack((original_target_vision_frame, temp_vision_frame))

	if preview_mode == 'face-by-face':
		target_crop_vision_frame, output_crop_vision_frame = create_face_by_face(reference_vision_frame, source_vision_frames, original_target_vision_frame, temp_vision_frame)
		return numpy.hstack((target_crop_vision_frame, output_crop_vision_frame))

	return temp_vision_frame


def create_face_by_face(reference_vision_frame : VisionFrame, source_vision_frames : List[VisionFrame], target_vision_frame : VisionFrame, temp_vision_frame : VisionFrame) -> Tuple[VisionFrame, VisionFrame]:
	target_faces = select_faces(reference_vision_frame[:, :, :3], source_vision_frames, [ target_vision_frame[:, :, :3] ])
	target_face = get_one_face(target_faces)

	if target_face:
		target_crop_vision_frame = extract_crop_frame(target_vision_frame, target_face)
		output_crop_vision_frame = extract_crop_frame(temp_vision_frame, target_face)

		if is_vision_frame(target_crop_vision_frame) and is_vision_frame(output_crop_vision_frame):
			target_crop_dimension = min(target_crop_vision_frame.shape[:2])
			target_crop_vision_frame = fit_cover_frame(target_crop_vision_frame, (target_crop_dimension, target_crop_dimension))
			output_crop_vision_frame = fit_cover_frame(output_crop_vision_frame, (target_crop_dimension, target_crop_dimension))
			return target_crop_vision_frame, output_crop_vision_frame

	empty_vision_frame = numpy.zeros((512, 512, 4), dtype = numpy.uint8)
	return empty_vision_frame, empty_vision_frame


def extract_crop_frame(vision_frame : VisionFrame, face : Face) -> Optional[VisionFrame]:
	start_x, start_y, end_x, end_y = map(int, face.bounding_box)
	padding_x = int((end_x - start_x) * 0.25)
	padding_y = int((end_y - start_y) * 0.25)
	start_x = max(0, start_x - padding_x)
	start_y = max(0, start_y - padding_y)
	end_x = max(0, end_x + padding_x)
	end_y = max(0, end_y + padding_y)
	crop_vision_frame = vision_frame[start_y:end_y, start_x:end_x]
	return crop_vision_frame


def prepare_output_frame(target_vision_frame : VisionFrame, temp_vision_frame : VisionFrame, temp_vision_mask : Mask) -> VisionFrame:
	fill_color = state_manager.get_item('background_remover_fill_color')
	clip_min = fill_color[-1] if fill_color else 0
	temp_vision_mask = temp_vision_mask.clip(clip_min, 255)
	temp_vision_frame = merge_vision_mask(temp_vision_frame, temp_vision_mask)
	temp_vision_frame = cv2.resize(temp_vision_frame, target_vision_frame.shape[1::-1])
	return temp_vision_frame


def resolve_real_target_path(target_path : str) -> str:
	if not target_path or not os.path.exists(target_path):
		return target_path

	from facefusion.filesystem import normalize_filename, resolve_real_file_path
	filename = os.path.basename(target_path)
	norm_target_name = normalize_filename(filename)

	# 1. Directly check OUTPUT PATH (the active working/saving directory)
	try:
		output_path = state_manager.get_item('output_path')
		if output_path:
			out_str = str(output_path)
			if os.path.isdir(out_str):
				direct_candidate = os.path.join(out_str, filename)
				if os.path.isfile(direct_candidate):
					return direct_candidate
				for entry in os.listdir(out_str):
					if normalize_filename(entry) == norm_target_name:
						cand = os.path.join(out_str, entry)
						if os.path.isfile(cand):
							return cand
	except Exception:
		pass

	# 2. Check TARGET_ORIGIN_MAP cache
	try:
		from facefusion.uis.components.target import TARGET_ORIGIN_MAP
		if target_path in TARGET_ORIGIN_MAP:
			return TARGET_ORIGIN_MAP[target_path]
		if filename in TARGET_ORIGIN_MAP:
			return TARGET_ORIGIN_MAP[filename]
		for k, v in TARGET_ORIGIN_MAP.items():
			if normalize_filename(k) == norm_target_name:
				return v
	except Exception:
		pass

	real_path = resolve_real_file_path(target_path)
	try:
		from facefusion.uis.components.target import TARGET_ORIGIN_MAP
		if real_path and real_path != target_path:
			TARGET_ORIGIN_MAP[target_path] = real_path
			TARGET_ORIGIN_MAP[filename] = real_path
	except Exception:
		pass

	return real_path


def save_preview_to_target() -> Any:
	reference_face_position_gallery = get_ui_component('reference_face_position_gallery')

	def fallback() -> Tuple[Any, ...]:
		fails = [ gradio.Button(value = '❌ Failed to Save (Check Target)'), gradio.skip() ]
		if reference_face_position_gallery:
			fails.append(gradio.Gallery())
		return tuple(fails)

	target_path = state_manager.get_item('target_path')
	if not target_path or not is_image(target_path):
		gradio.Warning('No active target image selected or target is a video.', duration = 2)
		return fallback()

	source_vision_frames = read_static_images(state_manager.get_item('source_paths'))
	source_audio_frame = create_empty_audio_frame()
	source_voice_frame = create_empty_audio_frame()

	target_vision_frame = read_static_image(target_path, 'rgba')
	reference_vision_frame = read_static_image(target_path)

	if not is_vision_frame(target_vision_frame) or not is_vision_frame(reference_vision_frame):
		gradio.Warning('Could not read target image from disk.', duration = 2)
		return fallback()

	# Lock the pristine unedited frame into cache before any disk overwrite
	original_frame = get_original_target_frame(target_path)
	real_target_path = resolve_real_target_path(target_path)
	if is_vision_frame(original_frame) and real_target_path:
		ORIGINAL_TARGET_FRAMES[real_target_path] = original_frame.copy()
		ORIGINAL_TARGET_FRAMES[os.path.basename(real_target_path)] = original_frame.copy()

	height, width = target_vision_frame.shape[:2]
	target_resolution = f'{width}x{height}'

	saved_vision_frame = None
	try:
		saved_vision_frame = process_preview_frame(
			reference_vision_frame,
			source_vision_frames,
			source_audio_frame,
			source_voice_frame,
			[ target_vision_frame ],
			'default',
			target_resolution
		)
	except Exception as exception:
		logger.error(f'Process preview frame failed: {exception}', __name__)

	if is_vision_frame(saved_vision_frame):
		if saved_vision_frame.ndim == 3 and saved_vision_frame.shape[2] == 4 and target_path.lower().endswith(('.jpg', '.jpeg')):
			saved_vision_frame = cv2.cvtColor(saved_vision_frame, cv2.COLOR_BGRA2BGR)

		real_target_path = resolve_real_target_path(target_path)
		written_real = False
		if real_target_path and os.path.exists(real_target_path) and os.path.abspath(real_target_path) != os.path.abspath(target_path):
			written_real = write_image(real_target_path, saved_vision_frame)

		written_temp = write_image(target_path, saved_vision_frame)

		if written_real or written_temp:
			read_static_image.cache_clear()
			clear_faces()
			target_filename = os.path.basename(real_target_path) if (written_real and real_target_path) else os.path.basename(target_path)
			if written_real:
				save_btn_out = gradio.Button(value = f'✅ Saved & Replaced: {target_filename}', variant = 'primary')
			else:
				save_btn_out = gradio.Button(value = f'⚠️ Replaced in Cache Only: {target_filename}', variant = 'primary')

			display_frame = cv2.cvtColor(saved_vision_frame, cv2.COLOR_BGRA2RGBA) if (saved_vision_frame.ndim == 3 and saved_vision_frame.shape[2] == 4) else cv2.cvtColor(saved_vision_frame, cv2.COLOR_BGR2RGB)
			set_hold_preview_frame(display_frame)

			success_results = [ save_btn_out, gradio.skip() ]
			if reference_face_position_gallery:
				try:
					from facefusion.uis.components.face_selector import update_reference_position_gallery
					success_results.append(update_reference_position_gallery())
				except Exception as ref_err:
					logger.error(f'Failed to update reference gallery: {ref_err}', __name__)
					success_results.append(gradio.Gallery())
			return tuple(success_results)
		else:
			return fallback()

	gradio.Error('Failed to process output image.', duration = 2)
	return fallback()


def batch_save_previews_to_targets(progress : gradio.Progress = gradio.Progress()) -> Tuple[Any, ...]:
	reference_face_position_gallery = get_ui_component('reference_face_position_gallery')

	def fallback(error_msg : str = '❌ Batch Replace Failed') -> Tuple[Any, ...]:
		fails = [
			gradio.Button(value = error_msg),
			gradio.skip()
		]
		if reference_face_position_gallery:
			fails.append(gradio.Gallery())
		return tuple(fails)

	target_uploads : List[str] = []
	try:
		from facefusion.uis.components.target import get_target_uploads
		target_uploads = get_target_uploads()
	except Exception:
		pass

	if not target_uploads:
		active_t = state_manager.get_item('target_path')
		if active_t:
			target_uploads = [ active_t ]

	image_targets = [ t for t in target_uploads if os.path.exists(t) and is_image(t) ]
	if not image_targets:
		gradio.Warning('No uploaded target images found to batch replace.', duration = 2)
		return fallback('❌ No Target Images Found')

	source_vision_frames = read_static_images(state_manager.get_item('source_paths'))
	source_audio_frame = create_empty_audio_frame()
	source_voice_frame = create_empty_audio_frame()

	current_target_path = state_manager.get_item('target_path')
	active_reference_frame = None
	if current_target_path and is_image(current_target_path) and os.path.exists(current_target_path):
		active_reference_frame = read_static_image(current_target_path)
	elif image_targets:
		active_reference_frame = read_static_image(image_targets[0])

	total = len(image_targets)
	replaced_count = 0
	last_active_replaced_frame = None
	active_real_path = resolve_real_target_path(current_target_path) if current_target_path else None

	for idx, t_path in enumerate(image_targets):
		filename = os.path.basename(t_path)
		progress((idx + 1) / total, desc = f"Replacing {idx + 1}/{total}: {filename}")

		real_t_path = resolve_real_target_path(t_path)
		orig_frame = get_original_target_frame(t_path)
		if not is_vision_frame(orig_frame):
			orig_frame = read_static_image(t_path, 'rgba')
		if is_vision_frame(orig_frame) and real_t_path:
			ORIGINAL_TARGET_FRAMES[real_t_path] = orig_frame.copy()
			ORIGINAL_TARGET_FRAMES[os.path.basename(real_t_path)] = orig_frame.copy()

		target_vision_frame = read_static_image(t_path, 'rgba')
		if not is_vision_frame(target_vision_frame):
			continue

		height, width = target_vision_frame.shape[:2]
		target_resolution = f'{width}x{height}'

		ref_frame = active_reference_frame if (is_vision_frame(active_reference_frame) and state_manager.get_item('face_selector_mode') == 'reference') else read_static_image(t_path)

		state_manager.set_item('target_path', t_path)
		saved_vision_frame = None
		try:
			saved_vision_frame = process_preview_frame(
				ref_frame,
				source_vision_frames,
				source_audio_frame,
				source_voice_frame,
				[ target_vision_frame ],
				'default',
				target_resolution
			)
		except Exception as err:
			logger.error(f'Failed to process {t_path}: {err}', __name__)
			continue

		if is_vision_frame(saved_vision_frame):
			if saved_vision_frame.ndim == 3 and saved_vision_frame.shape[2] == 4 and t_path.lower().endswith(('.jpg', '.jpeg')):
				saved_vision_frame = cv2.cvtColor(saved_vision_frame, cv2.COLOR_BGRA2BGR)

			written_real = False
			if real_t_path and os.path.exists(real_t_path) and os.path.abspath(real_t_path) != os.path.abspath(t_path):
				written_real = write_image(real_t_path, saved_vision_frame)

			written_temp = write_image(t_path, saved_vision_frame)

			if written_real or written_temp:
				replaced_count += 1
				is_current = False
				if current_target_path:
					if os.path.abspath(t_path) == os.path.abspath(current_target_path):
						is_current = True
					elif real_t_path and active_real_path and os.path.abspath(real_t_path) == os.path.abspath(active_real_path):
						is_current = True
				if is_current:
					last_active_replaced_frame = saved_vision_frame

	if current_target_path:
		state_manager.set_item('target_path', current_target_path)

	read_static_image.cache_clear()
	clear_faces()

	if replaced_count > 0:
		gradio.Info(f'Successfully replaced {replaced_count} target image(s) on disk.', duration = 3)
		batch_btn_out = gradio.Button(value = f'✅ Batch Replaced {replaced_count}/{total} Targets on Disk!')
		if last_active_replaced_frame is not None:
			display_frame = cv2.cvtColor(last_active_replaced_frame, cv2.COLOR_BGRA2RGBA) if (last_active_replaced_frame.ndim == 3 and last_active_replaced_frame.shape[2] == 4) else cv2.cvtColor(last_active_replaced_frame, cv2.COLOR_BGR2RGB)
			set_hold_preview_frame(display_frame)

		results = [ batch_btn_out, gradio.skip() ]
		if reference_face_position_gallery:
			try:
				from facefusion.uis.components.face_selector import update_reference_position_gallery
				results.append(update_reference_position_gallery())
			except Exception as ref_err:
				logger.error(f'Failed to update reference gallery: {ref_err}', __name__)
				results.append(gradio.Gallery())
		return tuple(results)

	return fallback('❌ Failed to Replace Targets')

