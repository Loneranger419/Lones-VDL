/** App-wide UI state that more than one component opens or reads. */
class UiState {
	/** The "Add download" dialog, opened from the top bar, Home, or empty states. */
	addOpen = $state(false);
	addUrl = $state('');

	openAdd(url = '') {
		this.addUrl = url;
		this.addOpen = true;
	}
}

export const ui = new UiState();
