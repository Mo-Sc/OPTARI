from napari import Viewer, run


def main() -> None:
	viewer = Viewer()
	viewer.window.add_plugin_dock_widget("patari", "PATARI Controls")
	run()


if __name__ == "__main__":
	main()
