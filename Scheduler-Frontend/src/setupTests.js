// jest-dom adds custom jest matchers for asserting on DOM nodes.
// allows you to do things like:
// expect(element).toHaveTextContent(/react/i)
// learn more: https://github.com/testing-library/jest-dom
import '@testing-library/jest-dom';

// Axios v1 is ESM-first; CRA/Jest (react-scripts 5) may fail to parse it.
// Mock axios globally for tests. Individual test files can override this mock.
jest.mock('axios', () => ({
	__esModule: true,
	default: {
		create: jest.fn(() => ({
			get: jest.fn(),
			post: jest.fn(),
			interceptors: {
				request: { use: jest.fn() },
				response: { use: jest.fn() },
			},
		})),
	},
}));