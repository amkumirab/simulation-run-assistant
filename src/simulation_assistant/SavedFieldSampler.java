import com.comsol.model.*;
import com.comsol.model.util.ModelUtil;
import java.nio.charset.StandardCharsets;
import java.io.*;
import java.util.*;
import java.util.zip.GZIPInputStream;

/** Saved solutions only. No mesh, study, solver run or model save calls. */
public class SavedFieldSampler {
    static String clean(String value) {
        return value == null ? "" : value.replaceAll("[\\p{Cntrl}]", " ");
    }

    static String[] fields(String row, int count) {
        String[] cells = row.split("\t", -1);
        if (cells.length != count) throw new IllegalArgumentException("Invalid request shape");
        return cells;
    }

    static List<String> payload(String encoded) throws Exception {
        List<String> rows = new ArrayList<String>();
        int size = 0;
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                new GZIPInputStream(new ByteArrayInputStream(Base64.getDecoder().decode(encoded))), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                size += line.length();
                if (size > 5000000) throw new IllegalArgumentException("Request exceeds 5 MB");
                rows.add(line);
            }
        }
        return rows;
    }

    static GeomSequence geometry(Model model) {
        GeomSequence geometry = null;
        for (String component : model.component().tags()) {
            for (String tag : model.component(component).geom().tags()) {
                if (geometry != null) throw new IllegalArgumentException("Multiple geometries are not supported in this increment");
                geometry = model.component(component).geom(tag);
            }
        }
        if (geometry == null || geometry.getSDim() != 3)
            throw new IllegalArgumentException("Only Cartesian 3D models are supported; no planar or axisymmetric mapping is inferred");
        return geometry;
    }

    static double coordinateScale(GeomSequence geometry) {
        String unit = geometry.lengthUnit();
        if (unit.equals("m")) return 1;
        if (unit.equals("cm")) return 100;
        if (unit.equals("mm")) return 1000;
        if (unit.equals("um")) return 1e6;
        if (unit.equals("nm")) return 1e9;
        throw new IllegalArgumentException("Unsupported geometry length unit: " + unit);
    }

    static String[] state(Model model, String dataset, String solver, int outer, int inner) {
        if (!model.result().dataset(dataset).getType().equals("Solution") ||
            !model.result().dataset(dataset).getString("solution").equals(solver))
            throw new IllegalArgumentException("Dataset/solver mismatch; select a direct Solution dataset");
        SolutionInfo info = model.sol(solver).getSolutioninfo();
        if (!info.isValid()) throw new IllegalArgumentException("Invalid saved solution information");
        boolean found = false;
        for (int value : info.getSolnum(outer, true)) if (value == inner) found = true;
        if (!found) throw new IllegalArgumentException("Saved outer/inner state not found");
        int[][] indices = new int[][] {{outer, inner}};
        String[] names;
        String[] units;
        double[] values;
        double[] imag;
        // Flat inner sweeps in 6.3 reject tuple-based parameter access.
        // Select the documented SolverSequence accessor only when no outer loop exists.
        if (info.getOuterSolnum().length == 0) {
            if (outer != 1) throw new IllegalArgumentException("No outer sweep; outer index must be 1");
            names = model.sol(solver).getPNames();
            values = model.sol(solver).getPVals(inner);
            imag = model.sol(solver).isRealPVals() ? new double[values.length] : model.sol(solver).getPValsImag(inner);
            units = new String[names.length];
            for (int i = 0; i < names.length; i++) units[i] = info.getUnit(names[i]);
        } else {
            names = info.getPNames(indices)[0];
            units = info.getUnits(indices)[0];
            values = info.getPvals(indices)[0];
            imag = info.getPvalsImag(indices)[0];
        }
        double frequency = Double.NaN;
        StringBuilder description = new StringBuilder();
        for (int i = 0; i < names.length; i++) {
            if (imag[i] != 0 || !Double.isFinite(values[i])) throw new IllegalArgumentException("Unsupported complex/nonfinite sweep parameter");
            if (i > 0) description.append("; ");
            description.append(clean(names[i])).append("=").append(values[i]).append(" ").append(clean(units[i]));
            if (names[i].equals("freq") && ("Hz".equals(units[i]) || "1/s".equals(units[i]))) frequency = values[i];
        }
        if (!Double.isFinite(frequency) || frequency <= 0) throw new IllegalArgumentException("Saved frequency in Hz is required");
        return new String[] {Double.toString(frequency), description.toString()};
    }

    static void catalog(Model model, StringBuilder output) {
        output.append("dataset\tsolver\touter\tinner\tfrequency_hz\tparameters\n");
        int count = 0;
        for (String dataset : model.result().dataset().tags()) {
            if (!model.result().dataset(dataset).getType().equals("Solution")) continue;
            String solver = model.result().dataset(dataset).getString("solution");
            if (model.sol(solver).isEmpty()) continue;
            try {
                SolutionInfo info = model.sol(solver).getSolutioninfo();
                if (!info.isValid()) continue;
                int[] outers = info.getOuterSolnum();
                if (outers.length == 0) outers = new int[] {1};
                for (int outer : outers) {
                    for (int inner : info.getSolnum(outer, true)) {
                        String[] details = state(model, dataset, solver, outer, inner);
                        if (++count > 10000) throw new IllegalArgumentException("Catalog exceeds 10000 states");
                        output.append(dataset+"\t"+solver+"\t"+outer+"\t"+inner+"\t"+details[0]+"\t"+details[1]+"\n");
                        if (output.length() > 5000000) throw new IllegalArgumentException("Catalog exceeds 5 MB");
                    }
                }
            } catch (IllegalArgumentException error) {
                throw error;
            } catch (Exception error) {
                throw new IllegalArgumentException("Cannot enumerate saved dataset " + dataset + ": " + clean(error.getMessage()));
            }
        }
    }

    static void extract(Model model, String request, String points, StringBuilder output, GeomSequence geometry) throws Exception {
        List<String> rows = payload(request);
        String[] symbols = fields(rows.get(0), 3);
        String[] expressions = new String[6];
        for (int i = 0; i < 3; i++) {
            if (!symbols[i].matches("(?:[A-Za-z][A-Za-z0-9_]{0,39}\\.){1,3}B"+"xyz".charAt(i)))
                throw new IllegalArgumentException("Invalid Cartesian field symbol");
            expressions[2*i] = "real("+symbols[i]+")";
            expressions[2*i+1] = "imag("+symbols[i]+")";
        }
        List<String> locations = payload(points);
        int count = locations.size()-1;
        if (count < 1 || count > 256 || rows.size() < 3 || rows.size() > 34) throw new IllegalArgumentException("Request limits exceeded");
        double[][] coordinates = new double[3][count];
        String[] ids = new String[count];
        double scale = coordinateScale(geometry);
        for (int j = 0; j < count; j++) {
            String[] row = fields(locations.get(j+1), 4);
            ids[j] = row[0];
            for (int axis = 0; axis < 3; axis++) coordinates[axis][j] = Double.parseDouble(row[axis+1])*scale;
        }
        output.append("scenario\tpoint_id\tbx_real\tbx_imag\tby_real\tby_imag\tbz_real\tbz_imag\n");
        for (int i = 2; i < rows.size(); i++) {
            String[] row = fields(rows.get(i), 7);
            String scenario = row[0], dataset = row[1], solver = row[2];
            int outer = Integer.parseInt(row[3]), inner = Integer.parseInt(row[4]);
            String[] details = state(model, dataset, solver, outer, inner);
            if (Double.parseDouble(details[0]) != Double.parseDouble(row[5]) || !details[1].equals(row[6]))
                throw new IllegalArgumentException("Saved state metadata changed; inspect again");
            String tag = "fieldSampler"+UUID.randomUUID().toString().replace("-", "");
            model.result().numerical().create(tag, "Interp");
            try {
                NumericalFeature feature = model.result().numerical(tag);
                feature.set("data", dataset);
                feature.selection().all();
                feature.set("expr", expressions);
                feature.set("unit", new String[] {"T", "T", "T", "T", "T", "T"});
                feature.set("solnum", new int[] {inner});
                feature.set("outersolnum", outer);
                feature.set("phase", 0);
                feature.set("ext", 0);
                feature.set("coorderr", "on");
                feature.set("matherr", "on");
                feature.setInterpolationCoordinates(coordinates);
                double[][][] values = feature.getData();
                if (values.length != 6) throw new IllegalArgumentException("Unexpected field component count");
                for (double[][] component : values) {
                    if (component.length != 1 || component[0].length != count)
                        throw new IllegalArgumentException("Unexpected solution/point count; no partial data accepted");
                    for (double value : component[0]) if (!Double.isFinite(value))
                        throw new IllegalArgumentException("Unavailable point or field; no partial data accepted");
                }
                for (int j = 0; j < count; j++) {
                    output.append(scenario+"\t"+ids[j]);
                    for (int k = 0; k < 6; k++) output.append("\t"+values[k][0][j]);
                    output.append("\n");
                }
            } finally {
                model.result().numerical().remove(tag);
            }
        }
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 5) throw new IllegalArgumentException("Expected private model, mode, request, output and points");
        Model model = ModelUtil.load("SavedFieldModel", args[0]);
        StringBuilder output = new StringBuilder();
        try {
            GeomSequence geometry = geometry(model);
            if (args[1].equals("catalog")) catalog(model, output);
            else if (args[1].equals("extract")) extract(model, args[2], args[4], output, geometry);
            else throw new IllegalArgumentException("Unsupported saved-field operation");
        } finally {
            ModelUtil.remove("SavedFieldModel");
        }
        // Use String output: COMSOL's console does not preserve byte-stream writers.
        System.out.println("FIELD_SAMPLING_BEGIN\n"+output.toString()+"FIELD_SAMPLING_OK");
    }
}
