// SPDX-License-Identifier: GPL-3.0-or-later
#include "common.h"
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#define rec_dup _dup
#define rec_dup2 _dup2
#define rec_fileno _fileno
#define rec_fdopen _fdopen
#else
#define rec_dup dup
#define rec_dup2 dup2
#define rec_fileno fileno
#define rec_fdopen fdopen
#endif

static FILE *frames;
static unsigned int step_number;
static int buttons;
static int dt_ticks;
static int report_camera;
static signed char last_tile[25]; // 1-based position on stable ground

static int travel_floor(int room, int pos) {
	int tile = get_tile(room, pos % 10, pos / 10);
	return tile == tiles_1_floor || tile == tiles_3_pillar ||
	       tile == tiles_19_torch || tile == tiles_14_debris;
}

static void travel_to(int room) {
	int pos = last_tile[room] - 1;
	if (pos < 0 || !travel_floor(room, pos)) {
		// A known room may have been seen only in mid-air or in a previous attempt.
		for (int i = 0; i < 30; ++i) {
			pos = (14 + i) % 30;
			if (travel_floor(room, pos)) break;
			if (i == 29) return;
		}
	}
	leave_guard();
	loadkid();
	Char.room = next_room = room;
	Char.curr_col = pos % 10;
	Char.curr_row = pos / 10;
	Char.x = x_bump[Char.curr_col + FIRST_ONSCREEN_COLUMN] + TILE_SIZEX;
	Char.y = y_land[Char.curr_row + 1];
	Char.fall_x = Char.fall_y = 0;
	Char.sword = sword_0_sheathed;
	seqtbl_offset_char(seq_2_stand);
	play_seq();
	savekid();
	clear_coll_rooms();
	exit_room_timer = 2;
	check_the_end();
}

void recorder_init(void) {
	if (!check_param("--recorder")) return;
	report_camera = check_param("--recorder-camera") != NULL;
	int fd = rec_dup(rec_fileno(stdout));
	if (fd < 0 || rec_dup2(rec_fileno(stderr), rec_fileno(stdout)) < 0) exit(2);
#ifdef _WIN32
	_setmode(fd, _O_BINARY);
	_setmode(rec_fileno(stdin), _O_BINARY);
#endif
	frames = rec_fdopen(fd, "wb");
	if (!frames) exit(2);
}

int recorder_active(void) {
	return frames != NULL;
}

int recorder_period(void) {
	return Kid.sword == sword_2_drawn ? custom->fight_speed : custom->base_speed;
}

void recorder_read_action(void) {
	int mask = fgetc(stdin);
	if (mask == EOF) exit(ferror(stdin) ? 2 : 0);
	if (mask > 88 || (mask > 56 && mask < 64) || mask == 32 ||
	    (mask < 32 && ((mask & 3) == 3 || (mask & 12) == 12))) exit(2);
	buttons = mask;
	dt_ticks = recorder_period();
	if (mask == 64) {
		// Restore a legacy camera without re-entering the room or respawning its guard.
		drawn_room = Kid.room;
		load_room_links();
		different_room = 1;
	} else if (mask > 32) {
		travel_to(mask > 64 ? mask - 64 : mask - 32);
	}
	++step_number;
}

void recorder_apply_action(void) {
	if (buttons > 32) {
		// do_paused cleared next_room after travel_to. draw_game_frame still
		// needs the destination. Bytes 33..56 replay historical saves verbatim.
		if (buttons >= 64 && different_room) next_room = drawn_room;
		control_x = control_y = control_shift = CONTROL_RELEASED;
		return;
	}
	control_x = (buttons & 1) ? CONTROL_HELD_LEFT : (buttons & 2) ? CONTROL_HELD_RIGHT : CONTROL_RELEASED;
	control_y = (buttons & 4) ? CONTROL_HELD_UP : (buttons & 8) ? CONTROL_HELD_DOWN : CONTROL_RELEASED;
	control_shift = (buttons & 16) ? CONTROL_HELD : CONTROL_RELEASED;
}

void recorder_frame(void) {
	// Observe support without get_tile(), which changes global collision state.
	int pos = Kid.curr_row * 10 + Kid.curr_col;
	if (Kid.room >= 1 && Kid.room <= 24 && Kid.curr_row >= 0 && Kid.curr_row < 3 &&
	    Kid.curr_col > 0 && Kid.curr_col < 9 && Kid.y == y_land[Kid.curr_row + 1]) {
		int tile = level.fg[(Kid.room - 1) * 30 + pos] & 31;
		if (tile == tiles_1_floor || tile == tiles_3_pillar || tile == tiles_19_torch || tile == tiles_14_debris)
			last_tile[Kid.room] = pos + 1;
	}
	// One post-render observation, including the native HUD, per simulation step.
	static unsigned char rgb[320 * 200 * 3];
	SDL_Surface *surface = onscreen_surface_;
	if (!surface || surface->w != 320 || surface->h != 200 ||
	    SDL_ConvertPixels(320, 200, surface->format->format, surface->pixels,
	                      surface->pitch, SDL_PIXELFORMAT_RGB24, rgb, 320 * 3) < 0) {
		fprintf(stderr, "recorder: RGB capture failed: %s\n", SDL_GetError());
		exit(2);
	}
	const char *end = "playing";
	if (current_level == custom->win_level && drawn_room == custom->win_room) end = "victory";
	else if (next_level != current_level) end = "level_complete";
	else if (hitp_curr == 0 || Kid.alive >= 0) end = "death";
	else if (rem_min == 0 && current_level < 13) end = "time_expired";

	if (fprintf(frames, "POP1 %u %d %d %d %s %d %d %d %d %d %d %d %d",
	            step_number, buttons, dt_ticks, recorder_period(), end, current_level, Kid.room,
	            Kid.x, Kid.y, Kid.direction, hitp_curr, Kid.frame, Kid.sword) < 0 ||
	    (report_camera && fprintf(frames, " %d", drawn_room) < 0) ||
	    fputc('\n', frames) == EOF || fwrite(rgb, 1, sizeof(rgb), frames) != sizeof(rgb) ||
	    fflush(frames) != 0) exit(2);
	if (strcmp(end, "playing") != 0) exit(0);
}
