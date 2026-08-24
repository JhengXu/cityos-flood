import unittest

import numpy as np

from backend.app.state_model import DEFAULT_ADJACENCIES, DistrictStateModel


class DistrictStateModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = DistrictStateModel()
        cls.ids = cls.model.district_ids

    def uniform_rain(self, values):
        return {did: list(values) for did in self.ids}

    def test_graph_has_ten_nodes_and_only_downhill_directed_edges(self):
        self.assertEqual(len(self.ids), 10)
        self.assertGreater(len(self.model.edges), 0)
        elevation = self.model.parameters["elevation_mean_m"]
        for edge in self.model.edges:
            source = self.model.index[edge.source]
            target = self.model.index[edge.target]
            self.assertGreater(elevation[source], elevation[target])
            self.assertGreater(edge.elevation_drop_m, 0.0)
            self.assertGreater(edge.distance_km, 0.0)
            self.assertGreater(edge.rate_per_h, 0.0)
            self.assertIn(frozenset((edge.source, edge.target)), DEFAULT_ADJACENCIES)
            self.assertLessEqual(edge.distance_km, 25.0)

    def test_local_dem_cache_prevents_flat_fallback_graph(self):
        elevations = self.model.parameters["elevation_mean_m"]
        self.assertGreater(float(np.ptp(elevations)), 50.0)
        baoan = self.model.index["baoan"]
        pingshan = self.model.index["pingshan"]
        self.assertLess(elevations[baoan], elevations[pingshan])

    def test_dry_start_stays_zero_and_non_negative(self):
        result = self.model.simulate(self.uniform_rain([0.0] * 6))
        np.testing.assert_array_equal(result["depth_mm"], 0.0)
        np.testing.assert_array_equal(result["storage_m3"], 0.0)
        self.assertTrue(result["audit"]["conservative"])

    def test_water_balance_closes_at_node_and_city_scales(self):
        storm = [0.0, 18.0, 55.0, 90.0, 40.0, 5.0, 0.0]
        rainfall = {
            did: [value * (0.8 + 0.04 * i) for value in storm]
            for i, did in enumerate(self.ids)
        }
        result = self.model.simulate(
            rainfall,
            tide_m=np.linspace(0.0, 1.4, len(storm)),
            pump_efficiency=0.75,
            drainage_control=0.85,
            initial_depth_mm={"baoan": 25.0, "nanshan": 10.0},
        )
        self.assertGreater(float(result["depth_mm"].max()), 0.0)
        self.assertGreaterEqual(float(result["depth_mm"].min()), 0.0)
        self.assertLess(result["audit"]["max_abs_node_residual_m3"], 1e-6)
        self.assertLess(abs(result["audit"]["closure_error_m3"]), 1e-5)
        self.assertTrue(result["audit"]["conservative"])

        lhs = result["storage_before_m3"] + result["rainfall_runoff_m3"]
        lhs += result["routed_in_m3"]
        rhs = (
            result["storage_m3"]
            + result["drainage_m3"]
            + result["routed_out_m3"]
            + result["external_outflow_m3"]
        )
        np.testing.assert_allclose(lhs, rhs, atol=1e-7, rtol=1e-12)

    def test_two_stage_storage_round_trip_is_continuous_and_monotone(self):
        depth = np.asarray([0.0, 25.0, 149.999, 150.0, 150.001, 500.0])[:, None]
        depth = np.repeat(depth, len(self.ids), axis=1)
        storage = self.model.depth_to_storage(depth)
        recovered = self.model.storage_to_depth(storage)
        np.testing.assert_allclose(recovered, depth, atol=1e-9, rtol=1e-12)
        self.assertTrue(np.all(np.diff(storage, axis=0) >= 0.0))

    def test_mobile_storage_can_leave_city_and_remains_in_mass_ledger(self):
        result = self.model.simulate(self.uniform_rain([90.0] * 10), tide_m=0.0)
        self.assertGreater(float(result["external_outflow_m3"].sum()), 0.0)
        self.assertTrue(result["audit"]["conservative"])
        self.assertGreater(result["audit"]["external_outflow_m3"], 0.0)

    def test_stronger_external_export_cannot_raise_peak_depth(self):
        rain = self.uniform_rain([70.0] * 12)
        weak = self.model.simulate(
            rain, parameter_overrides={"external_outflow_rate_h": 0.02}
        )
        strong = self.model.simulate(
            rain, parameter_overrides={"external_outflow_rate_h": 0.30}
        )
        self.assertLessEqual(float(strong["depth_mm"].max()), float(weak["depth_mm"].max()))
        self.assertGreaterEqual(
            float(strong["external_outflow_m3"].sum()),
            float(weak["external_outflow_m3"].sum()),
        )

    def test_vectorised_step_is_independent_of_district_iteration_order(self):
        reverse = DistrictStateModel(districts=list(reversed(self.model.districts)))
        storm = [12.0, 70.0, 25.0, 0.0]
        rainfall = {
            did: [v * (1.0 + self.model.index[did] / 20.0) for v in storm]
            for did in self.ids
        }
        normal_result = self.model.simulate(rainfall, drainage_control=0.45)
        reverse_result = reverse.simulate(rainfall, drainage_control=0.45)
        for did in self.ids:
            np.testing.assert_allclose(
                normal_result["depth_mm"][:, self.model.index[did]],
                reverse_result["depth_mm"][:, reverse.index[did]],
                atol=1e-10,
                rtol=1e-12,
            )

    def test_controls_and_tide_have_expected_physical_direction(self):
        rain = self.uniform_rain([45.0] * 8)
        healthy = self.model.simulate(
            rain, tide_m=0.0, pump_efficiency=1.0, drainage_control=1.0
        )
        impaired = self.model.simulate(
            rain, tide_m=1.5, pump_efficiency=0.25, drainage_control=0.55
        )
        coastal = self.model.parameters["coastal_exposure"] >= 0.3
        self.assertTrue(
            np.all(impaired["depth_mm"][-1, coastal] >= healthy["depth_mm"][-1, coastal])
        )
        self.assertGreater(
            float(impaired["depth_mm"][-1].sum()), float(healthy["depth_mm"][-1].sum())
        )

    def test_drainage_design_is_a_rainfall_intensity_threshold(self):
        # Disable graph routing to isolate local rainfall-to-drainage conversion.
        local = DistrictStateModel(max_downstream_edges=0)
        capacities = local.parameters["drainage_capacity_mm_h"]
        below = {
            did: [0.90 * capacities[local.index[did]]] for did in local.district_ids
        }
        above = {
            did: [1.10 * capacities[local.index[did]]] for did in local.district_ids
        }
        # Very low tide makes gravity availability effectively one, so the test
        # measures the design-intensity semantics rather than coastal backwater.
        below_result = local.simulate(below, tide_m=-2.0)
        above_result = local.simulate(above, tide_m=-2.0)
        np.testing.assert_allclose(below_result["depth_mm"], 0.0, atol=1e-8)
        self.assertTrue(np.all(above_result["depth_mm"] > 0.0))
        self.assertTrue(above_result["audit"]["conservative"])

    def test_parameter_ensemble_returns_ordered_quantiles_and_probabilities(self):
        result = self.model.simulate_ensemble(
            self.uniform_rain([10.0, 75.0, 60.0, 20.0, 0.0]),
            tide_m=[0.0, 0.3, 0.9, 1.2, 0.5],
            drainage_control=0.7,
            n_members=24,
            seed=7,
            thresholds_mm=(50.0, 150.0),
        )
        self.assertEqual(result["members_depth_mm"].shape, (24, 5, 10))
        self.assertTrue(np.all(result["depth_p10_mm"] <= result["depth_p50_mm"]))
        self.assertTrue(np.all(result["depth_p50_mm"] <= result["depth_p90_mm"]))
        for probability in result["exceedance_probability"].values():
            self.assertTrue(np.all((probability >= 0.0) & (probability <= 1.0)))
        self.assertTrue(result["audit"]["all_members_conservative"])
        self.assertGreater(float(np.std(result["members_depth_mm"][:, -1, :])), 0.0)
        self.assertEqual(
            set(result["sampled_parameters"]),
            {
                "runoff_coefficient",
                "drainage_capacity_mm_h",
                "ponding_fraction",
                "expanded_ponding_fraction",
                "external_outflow_rate_h",
                "routing_multiplier",
            },
        )
        self.assertTrue(
            all(value.shape == (24, 10) for value in result["sampled_parameters"].values())
        )

    def test_enkf_moves_observed_mean_towards_observation_and_accounts_increment(self):
        ensemble = self.model.simulate_ensemble(
            self.uniform_rain([20.0, 65.0, 30.0]),
            drainage_control=0.55,
            n_members=40,
            seed=11,
        )
        forecast_storage = ensemble["members_storage_m3"][:, -1, :]
        ponding_area = ensemble["members_ponding_area_m2"]
        expanded_area = ensemble["members_expanded_ponding_area_m2"]
        observed_id = "baoan"
        observed_idx = self.model.index[observed_id]
        forecast_depth = self.model.storage_to_depth(
            forecast_storage, ponding_area, expanded_area
        )
        observation = float(forecast_depth[:, observed_idx].mean() + 80.0)

        update = self.model.assimilate_enkf(
            forecast_storage,
            {observed_id: observation},
            observation_error_mm=5.0,
            localization_radius_km=25.0,
            seed=3,
            ponding_area_m2=ponding_area,
            expanded_ponding_area_m2=expanded_area,
        )
        np.testing.assert_allclose(update["forecast_depth_mm"], forecast_depth)
        before_error = abs(float(update["forecast_mean_depth_mm"][observed_idx]) - observation)
        after_error = abs(float(update["analysis_mean_depth_mm"][observed_idx]) - observation)
        self.assertLess(after_error, before_error)
        self.assertLessEqual(
            float(update["analysis_std_depth_mm"][observed_idx]),
            float(update["forecast_std_depth_mm"][observed_idx]),
        )
        self.assertTrue(np.all(update["analysis_storage_m3"] >= 0.0))
        np.testing.assert_allclose(
            update["analysis_storage_m3"] - update["forecast_storage_m3"],
            update["assimilation_increment_m3"],
            atol=1e-9,
        )
        np.testing.assert_allclose(
            update["ensemble_total_increment_m3"],
            update["assimilation_increment_m3"].sum(axis=1),
        )
        replay_with_other_seed = self.model.assimilate_enkf(
            forecast_storage,
            {observed_id: observation},
            observation_error_mm=5.0,
            localization_radius_km=25.0,
            seed=999,
            ponding_area_m2=ponding_area,
            expanded_ponding_area_m2=expanded_area,
        )
        self.assertEqual(update["filter"], "deterministic serial EnSRF")
        np.testing.assert_allclose(
            update["analysis_storage_m3"],
            replay_with_other_seed["analysis_storage_m3"],
            atol=0.0,
            rtol=0.0,
        )

    def test_invalid_inputs_are_rejected_instead_of_silently_clipped(self):
        with self.assertRaises(ValueError):
            self.model.simulate(self.uniform_rain([-1.0]))
        with self.assertRaises(ValueError):
            self.model.simulate(self.uniform_rain([10.0]), pump_efficiency=1.2)
        with self.assertRaises(ValueError):
            self.model.simulate({self.ids[0]: [10.0]})


if __name__ == "__main__":
    unittest.main()
