import glob
import os
import shutil
import subprocess
from typing import List, Optional, Tuple

import facefusion.choices


def get_file_size(file_path : str) -> int:
	if is_file(file_path):
		return os.path.getsize(file_path)
	return 0


def get_file_name(file_path : str) -> Optional[str]:
	file_name, _ = os.path.splitext(os.path.basename(file_path))

	if file_name:
		return file_name
	return None


def get_file_extension(file_path : str) -> Optional[str]:
	_, file_extension = os.path.splitext(file_path)

	if file_extension:
		return file_extension.lower()
	return None


def get_file_format(file_path : str) -> Optional[str]:
	file_extension = get_file_extension(file_path)

	if file_extension:
		if file_extension == '.jpg':
			return 'jpeg'
		if file_extension == '.tif':
			return 'tiff'
		if file_extension == '.mpg':
			return 'mpeg'
		return file_extension.lstrip('.')
	return None


def same_file_extension(first_file_path : str, second_file_path : str) -> bool:
	first_file_extension = get_file_extension(first_file_path)
	second_file_extension = get_file_extension(second_file_path)

	if first_file_extension and second_file_extension:
		return get_file_extension(first_file_path) == get_file_extension(second_file_path)
	return False


def is_file(file_path : str) -> bool:
	if file_path:
		return os.path.isfile(file_path)
	return False


def is_audio(audio_path : str) -> bool:
	return is_file(audio_path) and get_file_format(audio_path) in facefusion.choices.audio_formats


def has_audio(audio_paths : List[str]) -> bool:
	if audio_paths:
		return any(map(is_audio, audio_paths))
	return False


def are_audios(audio_paths : List[str]) -> bool:
	if audio_paths:
		return all(map(is_audio, audio_paths))
	return False


def is_image(image_path : str) -> bool:
	return is_file(image_path) and get_file_format(image_path) in facefusion.choices.image_formats


def has_image(image_paths : List[str]) -> bool:
	if image_paths:
		return any(is_image(image_path) for image_path in image_paths)
	return False


def are_images(image_paths : List[str]) -> bool:
	if image_paths:
		return all(map(is_image, image_paths))
	return False


def is_video(video_path : str) -> bool:
	return is_file(video_path) and get_file_format(video_path) in facefusion.choices.video_formats


def has_video(video_paths : List[str]) -> bool:
	if video_paths:
		return any(map(is_video, video_paths))
	return False


def are_videos(video_paths : List[str]) -> bool:
	if video_paths:
		return all(map(is_video, video_paths))
	return False


def filter_audio_paths(paths : List[str]) -> List[str]:
	if paths:
		return [ path for path in paths if is_audio(path) ]
	return []


def filter_image_paths(paths : List[str]) -> List[str]:
	if paths:
		return [ path for path in paths if is_image(path) ]
	return []


def copy_file(file_path : str, move_path : str) -> bool:
	if is_file(file_path):
		shutil.copy(file_path, move_path)
		return is_file(move_path)
	return False


def move_file(file_path : str, move_path : str) -> bool:
	if is_file(file_path):
		shutil.move(file_path, move_path)
		return not is_file(file_path) and is_file(move_path)
	return False


def remove_file(file_path : str) -> bool:
	if is_file(file_path):
		os.remove(file_path)
		return not is_file(file_path)
	return False


def resolve_file_paths(directory_path : str) -> List[str]:
	file_paths : List[str] = []

	if is_directory(directory_path):
		file_names_and_extensions = sorted(os.listdir(directory_path))

		for file_name_and_extension in file_names_and_extensions:
			if not file_name_and_extension.startswith(('.', '__')):
				file_path = os.path.join(directory_path, file_name_and_extension)
				file_paths.append(file_path)

	return file_paths


def resolve_file_pattern(file_pattern : str) -> List[str]:
	if in_directory(file_pattern):
		return sorted(glob.glob(file_pattern))
	return []


def is_directory(directory_path : str) -> bool:
	if directory_path:
		return os.path.isdir(directory_path)
	return False


def in_directory(file_path : str) -> bool:
	if file_path:
		directory_path = os.path.dirname(file_path)
		if directory_path:
			return not is_directory(file_path) and is_directory(directory_path)
	return False


def create_directory(directory_path : str) -> bool:
	if directory_path and not is_file(directory_path):
		os.makedirs(directory_path, exist_ok = True)
		return is_directory(directory_path)
	return False


def remove_directory(directory_path : str) -> bool:
	if is_directory(directory_path):
		shutil.rmtree(directory_path, ignore_errors = True)
		return not is_directory(directory_path)
	return False


def resolve_relative_path(path : str) -> str:
	return os.path.abspath(os.path.join(os.path.dirname(__file__), path))


def resolve_real_file_path(file_path : str) -> str:
	if not file_path or not os.path.exists(file_path):
		return file_path

	norm_path = os.path.abspath(file_path)
	is_temp = any(seg in norm_path.lower() for seg in [
		'/gradio/',
		'/tmpdir/',
		'/tmp/',
		'/temp/',
		'/var/folders/',
		'appdata/local/temp'
	])
	if not is_temp:
		return file_path

	filename = os.path.basename(file_path)

	# 1. Check active output_path directory first
	try:
		from facefusion import state_manager
		output_path = state_manager.get_item('output_path')
		if output_path:
			out_str = str(output_path)
			if os.path.isdir(out_str):
				direct_candidate = os.path.join(out_str, filename)
				if os.path.isfile(direct_candidate):
					return direct_candidate
	except Exception:
		pass

	try:
		target_size = os.path.getsize(file_path)
	except Exception:
		target_size = 0

	# 2. macOS Spotlight search using mdfind
	mdfind_bin = shutil.which('mdfind') or '/usr/bin/mdfind'
	if os.path.exists(mdfind_bin):
		queries = [
			f'kMDItemFSName == "{filename}"',
			f'-name "{filename}"'
		]
		for q in queries:
			try:
				cmd = [ mdfind_bin, q ] if not q.startswith('-') else [ mdfind_bin ] + q.split(maxsplit = 1)
				proc = subprocess.run(cmd, stdout = subprocess.PIPE, stderr = subprocess.PIPE, text = True, timeout = 3)
				if proc.returncode == 0:
					matches = [ line.strip() for line in proc.stdout.splitlines() if line.strip() ]
					real_matches = [
						m for m in matches
						if os.path.isfile(m) and not any(t in m.lower() for t in [ '/gradio/', '/tmpdir/', '/tmp/', '/temp/', '/var/folders/', 'appdata/local/temp' ])
					]
					if real_matches:
						def score_match(m : str) -> Tuple[int, float]:
							try:
								exact_size = 1 if target_size > 0 and os.path.getsize(m) == target_size else 0
								mtime = os.path.getmtime(m)
								return (exact_size, mtime)
							except Exception:
								return (0, 0.0)

						real_matches.sort(key = score_match, reverse = True)
						return real_matches[0]
			except Exception:
				pass

	# 3. Check mounted volumes if needed
	if os.path.exists('/Volumes'):
		try:
			for vol in os.listdir('/Volumes'):
				vol_path = os.path.join('/Volumes', vol)
				if os.path.isdir(vol_path) and not vol.startswith('.'):
					direct = os.path.join(vol_path, filename)
					if os.path.isfile(direct):
						return direct

					for root, dirs, files in os.walk(vol_path):
						depth = root[len(vol_path):].count(os.sep)
						if depth > 4:
							dirs.clear()
							continue
						if filename in files:
							candidate = os.path.join(root, filename)
							if os.path.isfile(candidate):
								return candidate
		except Exception:
			pass

	return file_path

