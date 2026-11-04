import com.comsol.model.*;
import com.comsol.model.util.ModelUtil;
import java.util.*;

/** Read finalized geometry only. No build, mesh, solver or model-save calls. */
public class SavedGeometryInspector {
    static String clean(String text) {
        return text == null ? "" : text.replaceAll("[^\\x20-\\x7e]", "?");
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 5 || !args[1].equals("geometry")) throw new IllegalArgumentException("Invalid inspection request");
        Model model = ModelUtil.load("GeometrySnapshot", args[0]);
        StringBuilder output = new StringBuilder();
        try {
            GeomSequence geometry = null;
            String component = "", tag = "";
            for (String c : model.component().tags()) for (String g : model.component(c).geom().tags()) {
                if (geometry != null) throw new IllegalArgumentException("Select a model with one geometry");
                geometry = model.component(c).geom(g); component = c; tag = g;
            }
            if (geometry == null || geometry.getSDim() != 3 || !geometry.exists())
                throw new IllegalArgumentException("Saved finalized Cartesian 3D geometry is required; no build starts");
            int count = geometry.getNDomains();
            if (count < 1 || count > 256) throw new IllegalArgumentException("Geometry needs 1-256 domains");
            output.append("geometry\t"+component+"\t"+tag+"\t"+geometry.lengthUnit()+"\t"+clean(ModelUtil.getComsolVersion())+"\n");
            output.append("domain\tselections\txmin\txmax\tymin\tymax\tzmin\tzmax\n");
            GeomMeasureFinal measure = geometry.measureFinal();
            for (int domain = 1; domain <= count; domain++) {
                List<String> names = new ArrayList<String>();
                for (String selection : model.component(component).selection().tags()) {
                    Selection selected = model.component(component).selection(selection);
                    boolean hasDomains = false;
                    for (int dimension : selected.dimension()) if (dimension == 3) hasDomains = true;
                    if (!hasDomains) continue;
                    for (int id : selected.entities(3)) if (id == domain) {
                        names.add(clean(selection)); break;
                    }
                }
                measure.selection().geom(tag, 3);
                measure.selection().set(new int[] {domain});
                double[] box = measure.getBoundingBox();
                if (box.length != 6) throw new IllegalArgumentException("Missing 3D domain bounds");
                output.append(domain+"\t"+String.join(", ", names));
                for (double value : box) {
                    if (!Double.isFinite(value)) throw new IllegalArgumentException("Nonfinite domain bounds");
                    output.append("\t"+value);
                }
                output.append("\n");
            }
        } finally { ModelUtil.remove("GeometrySnapshot"); }
        System.out.println("GEOMETRY_INSPECTION_BEGIN\n"+output.toString()+"GEOMETRY_INSPECTION_OK");
    }
}
